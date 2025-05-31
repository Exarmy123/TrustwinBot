import os
import asyncio
import random
import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from supabase import create_client
from tronpy import Tron
from tronpy.keys import PrivateKey

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY")
TRON_NODE = os.getenv("TRON_NODE") or "https://api.trongrid.io"
TICKET_PRICE = 4.0  # USD
REFERRAL_COMMISSION = 1.0
ADMIN_COMMISSION = 1.0
DRAW_PRIZE = 2.0
DAILY_DRAW_HOUR = 0
DAILY_DRAW_MINUTE = 1

# --- Init ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
tron = Tron(provider=TRON_NODE)
admin_wallet = os.getenv("USDT_ADDRESS")
private_key = PrivateKey(bytes.fromhex(TRON_PRIVATE_KEY))

# --- Register User ---
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    user_id = msg.from_user.id
    username = msg.from_user.username or "NoUsername"
    args = msg.get_args()
    ref = args if args else None

    existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not existing.data:
        supabase.table("users").insert({"user_id": user_id, "username": username, "referred_by": ref}).execute()

    await msg.reply(
        f"🎉 Welcome to TrustWin Lottery!\n"
        f"🎟️ Each ticket costs {TICKET_PRICE}$ (USDT TRC20).\n"
        "Use /buy to purchase tickets."
    )

# --- Buy Ticket ---
@dp.message_handler(commands=["buy"])
async def buy(msg: types.Message):
    user_id = msg.from_user.id
    await msg.reply(
        f"💰 Send exactly {TICKET_PRICE}$ in USDT (TRC20) to:\n"
        f"🔐 Wallet Address:\n"
        f"`{admin_wallet}`\n\n"
        "📩 After sending, use /confirm to proceed.",
        parse_mode="Markdown"
    )

# --- Confirm Payment ---
@dp.message_handler(commands=["confirm"])
async def confirm(msg: types.Message):
    user_id = msg.from_user.id
    supabase.table("transactions").insert({"user_id": user_id, "amount": TICKET_PRICE, "status": "pending"}).execute()
    await msg.reply("⏳ Payment submitted. Admin will verify soon.")

# --- Admin Confirm & Commission ---
@dp.message_handler(commands=["admin_confirm"])
async def admin_confirm(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.reply("🚫 Unauthorized")

    try:
        args = msg.text.split()
        user_id = int(args[1])

        supabase.table("transactions").update({"status": "confirmed"}).eq("user_id", user_id).eq("status", "pending").execute()

        # Referral Payment
        user = supabase.table("users").select("*").eq("user_id", user_id).execute().data[0]
        ref_id = user.get("referred_by")
        if ref_id:
            supabase.table("transactions").insert({"user_id": ref_id, "amount": REFERRAL_COMMISSION, "status": "referral"}).execute()

        await msg.reply("✅ Ticket issued and referral rewarded.")
    except Exception:
        await msg.reply("❗ Usage: /admin_confirm <user_id>")

# --- View Tickets ---
@dp.message_handler(commands=["tickets"])
async def tickets(msg: types.Message):
    user_id = msg.from_user.id
    confirmed = supabase.table("transactions").select("*").eq("user_id", user_id).eq("status", "confirmed").execute()
    count = len(confirmed.data) if confirmed.data else 0
    await msg.reply(f"🎫 You have {count} confirmed ticket(s).")

# --- Referral Link ---
@dp.message_handler(commands=["refer"])
async def refer(msg: types.Message):
    user_id = msg.from_user.id
    bot_info = await bot.get_me()
    await msg.reply(f"🔗 Your referral link:\nhttps://t.me/{bot_info.username}?start={user_id}")

# --- Admin Broadcast ---
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
        except Exception:
            pass
    await msg.reply(f"📤 Broadcast sent to {count} users.")

# --- Daily Draw ---
async def draw_winner():
    today = datetime.date.today().isoformat()
    txs = supabase.table("transactions").select("*").eq("status", "confirmed").execute().data
    if not txs:
        return
    winner_id = random.choice([tx["user_id"] for tx in txs])

    supabase.table("transactions").insert({
        "user_id": winner_id,
        "amount": DRAW_PRIZE,
        "status": "win",
        "date": today
    }).execute()

    try:
        await bot.send_message(winner_id, f"🏆 You won the TrustWin draw! Prize: {DRAW_PRIZE}$")
    except Exception:
        pass

# --- Schedule Daily Draw ---
async def schedule_draw():
    while True:
        now = datetime.datetime.now()
        if now.hour == DAILY_DRAW_HOUR and now.minute == DAILY_DRAW_MINUTE:
            await draw_winner()
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- Run Bot ---
async def main():
    print("🤖 TrustWin Bot is running...")
    asyncio.create_task(schedule_draw())
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
