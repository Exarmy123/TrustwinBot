import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from supabase import create_client, Client
import logging
import asyncio

# Logging
logging.basicConfig(level=logging.INFO)

# ENV Secrets
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY")

# Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Main Buttons
main_buttons = [
    ["Start", "Buy Ticket"],
    ["My Referral", "My Tickets"],
    ["Withdraw", "Check Result"],
    ["Leaderboard", "How It Works"],
    ["Support"]
]

reply_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton(text) for text in row] for row in main_buttons], resize_keyboard=True
)

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    name = user.full_name
    username = user.username or "N/A"

    # Store or update user
    supabase.table("users").upsert({"id": uid, "name": name, "username": username}).execute()

    welcome_msg = f"""
🎉 *Welcome to TrustWin, {name}!* 🎉

✅ *Play daily* to win crypto prizes
✅ *Earn lifetime referral* income
✅ *Withdraw instantly* in USDT (TRC20)

Tap any button below to begin 👇
"""
    await update.message.reply_text(welcome_msg, reply_markup=reply_keyboard, parse_mode='Markdown')

# How It Works
async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    how_msg = open("how_it_works.txt", "r").read()
    await update.message.reply_text(how_msg, parse_mode='Markdown')

# Command Aliases (if needed)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "start" in text:
        await start(update, context)
    elif "how it works" in text:
        await how_it_works(update, context)
    else:
        await update.message.reply_text("⚠️ Feature under development.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logging.info("🤖 Bot is running...")
    app.run_polling()
