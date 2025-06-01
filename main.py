# TrustWin Lottery Bot - FINAL FULL FUNCTIONAL VERSION (WEBHOOK SUPPORTED)

import os
import asyncio
import random
import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from fastapi import FastAPI, Request
from supabase import create_client
from tronpy import Tron
from tronpy.providers import HTTPProvider
from tronpy.keys import PrivateKey

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
TICKET_PRICE = 4.0
REFERRAL_COMMISSION = 1.0
ADMIN_COMMISSION = 1.0
DRAW_PRIZE = 2.0
DAILY_DRAW_HOUR = 0
DAILY_DRAW_MINUTE = 1

# --- Init ---
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

provider = HTTPProvider(endpoint_uri="https://api.trongrid.io", api_key=TRONGRID_API_KEY)
tron = Tron(provider)

admin_wallet = os.getenv("USDT_ADDRESS")
private_key = PrivateKey(bytes.fromhex(TRON_PRIVATE_KEY))

# --- Commands ---
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    user_id = msg.from_user.id
    username = msg.from_user.username or "NoUsername"
    args = msg.get_args()
    ref = args if args and args.isdigit() and int(args) != user_id else None

    existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not existing.data:
        supabase.table("users").insert({"user_id": user_id, "username": username, "referred_by": ref}).execute()

    bot_info = await bot.get_me()
    refer_link = f"https://t.me/{bot_info.username}?start={user_id}"
    await msg.reply(f"🎉 Welcome to TrustWin Lottery!\n🎟️ Each ticket costs {TICKET_PRICE}$ (USDT TRC20).\nUse /buy to purchase tickets.\n\n🔗 Your referral link:\n{refer_link}")

@dp.message_handler(commands=["buy"])
async def buy(msg: types.Message):
    await msg.reply(
        f"💰 Send exactly {TICKET_PRICE}$ in USDT (TRC20) to:\n🔐 Wallet Address:\n`{admin_wallet}`\n\n📩 After sending, use /confirm YourWalletAddress to proceed.",
        parse_mode="Markdown"
    )

@dp.message_handler(commands=["confirm"])
async def confirm(msg: types.Message):
    user_id = msg.from_user.id
    user_wallet = msg.text.replace("/confirm", "").strip()
    if not user_wallet:
        return await msg.reply("❗ Usage: /confirm YourWalletAddress")

    supabase.table("transactions").insert({"user_id": user_id, "amount": TICKET_PRICE, "status": "pending", "wallet": user_wallet}).execute()
    await msg.reply("⏳ Payment submitted. Admin will verify soon.")

@dp.message_handler(commands=["admin_confirm"])
async def admin_confirm(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.reply("🚫 Unauthorized")
    try:
        args = msg.text.split()
        user_id = int(args[1])

        txs = supabase.table("transactions").select("*").eq("user_id", user_id).eq("status", "pending").execute().data
        if not txs:
            return await msg.reply("⚠️ No pending transaction for this user.")

        tx = txs[0]
        user_wallet = tx.get("wallet")
        supabase.table("transactions").update({"status": "confirmed"}).eq("user_id", user_id).eq("status", "pending").execute()
        tron.trx.transfer(private_key, user_wallet, int(DRAW_PRIZE * 1_000_000))

        user = supabase.table("users").select("*").eq("user_id", user_id).execute().data[0]
        ref_id = user.get("referred_by")
        if ref_id:
            ref_user = supabase.table("users").select("*").eq("user_id", ref_id).execute().data
            if ref_user:
                ref_wallet_tx = supabase.table("transactions").select("*").eq("user_id", ref_id).eq("status", "confirmed").execute().data
                if ref_wallet_tx:
                    ref_wallet = ref_wallet_tx[-1].get("wallet")
                    if ref_wallet:
                        tron.trx.transfer(private_key, ref_wallet, int(REFERRAL_COMMISSION * 1_000_000))
                        supabase.table("transactions").insert({"user_id": ref_id, "amount": REFERRAL_COMMISSION, "status": "referral"}).execute()
        await msg.reply("✅ Ticket issued. Referral rewarded if applicable.")
    except:
        await msg.reply("❗ Usage: /admin_confirm <user_id>")

@dp.message_handler(commands=["tickets"])
async def tickets(msg: types.Message):
    user_id = msg.from_user.id
    confirmed = supabase.table("transactions").select("*").eq("user_id", user_id).eq("status", "confirmed").execute()
    await msg.reply(f"🎫 You have {len(confirmed.data)} confirmed ticket(s).")

@dp.message_handler(commands=["refer"])
async def refer(msg: types.Message):
    user_id = msg.from_user.id
    bot_info = await bot.get_me()
    await msg.reply(f"🔗 Your referral link:\nhttps://t.me/{bot_info.username}?start={user_id}")

@dp.message_handler(commands=["broadcast"])
async def broadcast(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.reply("🚫 Unauthorized")

    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        return await msg.reply("❗ Usage: /broadcast Your message here")

    users = supabase.table("users").select("user_id").execute().data
    count = 0
    for user in users:
        try:
            await bot.send_message(user["user_id"], text)
            count += 1
        except:
            pass
    await msg.reply(f"📤 Broadcast sent to {count} users.")

async def draw_winner():
    today = datetime.date.today().isoformat()
    txs = supabase.table("transactions").select("*").eq("status", "confirmed").execute().data
    if not txs:
        return

    winner_tx = random.choice(txs)
    winner_id = winner_tx["user_id"]
    winner_wallet = winner_tx.get("wallet")

    supabase.table("transactions").insert({"user_id": winner_id, "amount": DRAW_PRIZE, "status": "win", "date": today}).execute()
    tron.trx.transfer(private_key, winner_wallet, int(DRAW_PRIZE * 1_000_000))
    try:
        await bot.send_message(winner_id, f"🏆 Congratulations! You won the daily jackpot of {DRAW_PRIZE}$!")
    except:
        pass

async def schedule_draw():
    while True:
        now = datetime.datetime.now()
        if now.hour == DAILY_DRAW_HOUR and now.minute == DAILY_DRAW_MINUTE:
            await draw_winner()
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- Webhook setup ---
app = FastAPI()
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(schedule_draw())

@app.post(WEBHOOK_PATH)
async def handle_update(request: Request):
    body = await request.body()
    update = types.Update(**request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "TrustWin Lottery Bot is Running."}
