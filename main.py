import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# In-memory user data storage (replace with DB in real apps)
users = {}

WELCOME_MESSAGE = """
(यहाँ ऊपर वाला पूरा welcome message paste करें)
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        users[user_id] = {"tickets": [], "referrer": None, "balance": 0}
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')

async def main():
    application = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()
    application.add_handler(CommandHandler("start", start))
    print("Bot started...")
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
