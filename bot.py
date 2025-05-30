import os
import threading
from flask import Flask
from telegram.ext import Updater, CommandHandler

# Flask app for Render health check
app = Flask(__name__)

@app.route('/')
def home():
    return "TrustWin Telegram Bot is Live!"

# Telegram bot logic
def start_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Error: BOT_TOKEN not set in environment variables.")
        return

    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    def start(update, context):
        update.message.reply_text("🙏 Welcome to TrustWin Lottery Bot!")

    dp.add_handler(CommandHandler("start", start))

    # Start polling
    updater.start_polling()
    updater.idle()

# Run both Flask server and Telegram bot
if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
