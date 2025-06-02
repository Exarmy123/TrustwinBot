# TrustWin Telegram Lottery Bot - Full Code with ENV and Supabase Integration

import os
import random
import logging
import asyncio
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from supabase import create_client, Client

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Supabase setup
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Logging
logging.basicConfig(level=logging.INFO)

TICKET_PRICE = 4.0
REFERRAL_PERCENT = 0.25
TAX_PERCENT = 0.25
POOL_PER_TICKET = 2.0

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref = context.args[0] if context.args else ""
    supabase.table("users").upsert({"id": user.id, "username": user.username, "ref": ref}).execute()
    await update.message.reply_text(
        f"Welcome {user.first_name}!\n\n🎟 Buy tickets and win crypto daily!\n💸 Lifetime 25% referral income!\nUse /buy to get started."
    )

# Buy command
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    supabase.table("tickets").insert({"user_id": user.id, "timestamp": datetime.utcnow().isoformat()}).execute()
    await update.message.reply_text(
        "✅ Ticket purchased successfully!\n🏆 You’re now eligible for the next draw."
    )

# Daily winner draw (called by admin manually)
async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    today = datetime.utcnow().date()
    tix = supabase.table("tickets").select("*").gte("timestamp", today.isoformat()).execute().data
    if not tix:
        await update.message.reply_text("No tickets sold today.")
        return
    winner = random.choice(tix)
    user_id = winner['user_id']
    supabase.table("winners").insert({"user_id": user_id, "amount": len(tix)*POOL_PER_TICKET}).execute()
    await context.bot.send_message(chat_id=user_id, text=f"🎉 You’ve won today’s lottery! You get {len(tix)*POOL_PER_TICKET} USDT!")
    await update.message.reply_text(f"🏆 Winner: {user_id}\nPrize: {len(tix)*POOL_PER_TICKET} USDT")

# Admin broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = " ".join(context.args)
    users = supabase.table("users").select("id").execute().data
    for u in users:
        try:
            await context.bot.send_message(chat_id=u['id'], text=msg)
        except:
            continue
    await update.message.reply_text("📣 Broadcast sent.")

# Fake leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    board = [
        (f"@MegaWin{i}", random.randint(1000, 50000)) for i in range(1, 51)
    ]
    msg = "🏆 Top 50 Winners:\n\n"
    for i, (name, amt) in enumerate(board, 1):
        msg += f"{i}. {name} — {amt} USDT\n"
    await update.message.reply_text(msg)

# Help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /buy to buy a ticket, /leaderboard to view winners.")

# Manual GET updates test (for troubleshooting only)
def check_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    response = requests.get(url)
    print(response.json())

# Main
if __name__ == '__main__':
    check_updates()  # For debug only. Remove or comment out in production.
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("draw", draw))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("help", help_command))
    print("🤖 TrustWin Bot is running...")
    app.run_polling()
