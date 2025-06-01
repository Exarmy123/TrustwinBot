import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from supabase import create_client, Client

# Logging setup
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Main buttons for the reply keyboard
main_buttons = [
    ["Start", "Buy Ticket"],
    ["My Referral", "My Tickets"],
    ["Withdraw", "Check Result"],
    ["Leaderboard", "How It Works"],
    ["Support"]
]

reply_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton(text) for text in row] for row in main_buttons],
    resize_keyboard=True
)

# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    name = user.full_name
    username = user.username or "N/A"

    # Upsert user to Supabase
    try:
        supabase.table("users").upsert({"id": uid, "name": name, "username": username}).execute()
        logging.info(f"User {uid} upserted successfully.")
    except Exception as e:
        logging.error(f"Error upserting user {uid}: {e}")

    welcome_msg = f"""
🎉 *Welcome to TrustWin, {name}!* 🎉

✅ *Play daily* to win crypto prizes
✅ *Earn lifetime referral* income
✅ *Withdraw instantly* in USDT (TRC20)

Tap any button below to begin 👇
"""
    await update.message.reply_text(welcome_msg, reply_markup=reply_keyboard, parse_mode='Markdown')

# How It Works handler
async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open("how_it_works.txt", "r", encoding="utf-8") as f:
            how_msg = f.read()
    except FileNotFoundError:
        how_msg = "Sorry, the 'How It Works' information is not available right now."
    await update.message.reply_text(how_msg, parse_mode='Markdown')

# Generic text handler for commands via buttons
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "start" in text:
        await start(update, context)
    elif "how it works" in text:
        await how_it_works(update, context)
    else:
        await update.message.reply_text("⚠️ Feature under development.")

# Example update command for admin (optional)
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    # Implement update logic here, e.g., pull latest code, restart bot, etc.
    await update.message.reply_text("✅ Update command received. Feature coming soon.")

# Main function to run the bot
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", update_command))  # Optional admin command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logging.info("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
