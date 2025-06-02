# TrustWin Telegram Lottery Bot - Full Code with ENV and Supabase Integration (Updated)

import os
import random
import logging
import asyncio
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

# Constants
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
        f"Welcome {user.first_name}!
\n🎟 Buy tickets and win crypto daily!
💸 Lifetime 25% referral income!
Use /buy to get started."
    )

# Buy ticket command
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ticket = {
        "user_id": user.id,
        "timestamp": datetime.utcnow().isoformat(),
        "username": user.username
    }
    supabase.table("tickets").insert(ticket).execute()
    await update.message.reply_text(
        "✅ Ticket purchased successfully!\n🏆 You’re now eligible for the next draw."
    )

# Daily draw - Admin only
async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to run the draw.")
        return
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    tickets_response = supabase.table("tickets").select("*").gte("timestamp", today.isoformat()).execute()
    tickets = tickets_response.data
    if not tickets:
        await update.message.reply_text("No tickets sold today.")
        return
    winner = random.choice(tickets)
    prize = len(tickets) * POOL_PER_TICKET
    supabase.table("winners").insert({"user_id": winner['user_id'], "amount": prize}).execute()
    await context.bot.send_message(chat_id=winner['user_id'], text=f"🎉 You’ve won today’s lottery! You get {prize} USDT!")
    await update.message.reply_text(f"🏆 Winner: {winner['user_id']}\nPrize: {prize} USDT")

# Admin broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to broadcast messages.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a message to broadcast.")
        return
    msg = " ".join(context.args)
    users = supabase.table("users").select("id").execute().data
    for u in users:
        try:
            await context.bot.send_message(chat_id=u['id'], text=msg)
        except:
            continue
    await update.message.reply_text("📣 Broadcast sent successfully.")

# Fake leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    board = [(f"@MegaWin{i}", random.randint(1000, 50000)) for i in range(1, 51)]
    msg = "🏆 Top 50 Winners:\n\n"
    for i, (name, amt) in enumerate(board, 1):
        msg += f"{i}. {name} — {amt} USDT\n"
    await update.message.reply_text(msg)

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Available Commands:\n"
        "/start - Start the bot\n"
        "/buy - Buy a lottery ticket\n"
        "/leaderboard - View top winners\n"
        "/help - Show this help message"
    )

# Main entry point
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("draw", draw))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("help", help_command))
    print("🤖 TrustWin Bot is running...")
    app.run_polling()

# 🧪 To manually test updates:
# import requests
# TOKEN = 'YOUR_BOT_TOKEN'
# url = f'https://api.telegram.org/bot{TOKEN}/getUpdates'
# response = requests.get(url)
# print(response.json())
