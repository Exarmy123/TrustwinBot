# TrustWin Lottery Telegram Bot - FINAL VERSION (Render Ready)
# Note: Replace ALL values marked with 'YOUR_' below with actual data or environment variables.

import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime
import asyncio

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
if ADMIN_ID_STR is None:
    raise ValueError("ADMIN_ID environment variable not set")
ADMIN_ID = int(ADMIN_ID_STR)

# Mockup data (should be replaced with DB or Blockchain integration)
past_winners = [
    ("@MegaWinBot", "50,000 USDT", "2025-05-13"),
    ("@CryptoQueen", "42,000 USDT", "2025-05-09"),
    ("@TRXKing", "37,500 USDT", "2025-05-07"),
    ("@legendLuck", "33,000 USDT", "2025-05-05"),
]

# --- Start Command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 What is TrustWin?", callback_data='about_trustwin')],
        [InlineKeyboardButton("🎟 Buy Ticket Now", url="https://t.me/YOURBOT?start=ticket")],
        [InlineKeyboardButton("💸 Refer & Earn", callback_data='referral_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "🎉 *Welcome to TrustWin* 🎉\n\n"
        "📜 *How TrustWin Works*\n\n"
        "Powered by a Decentralized Blockchain Smart Contract, Social Welfare Trust, and Protected by the Global Crypto Security Network.\n\n"
        "🔐 No Human Control | 💸 Daily Crypto Rewards | 🌍 Global Transparency Guaranteed\n\n"
        "👇 Click below to explore more 👇"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# --- Callback Handler ---
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'about_trustwin':
        await query.edit_message_text(
            text=(
                "🎯 *What is TrustWin?*\n\n"
                "TrustWin is a decentralized crypto-based lottery game that:\n"
                "- 🏆 Awards daily prizes via smart contract\n"
                "- 💵 Pays instant referral income\n"
                "- 🌍 Is open to all globally with no human control\n"
                "\n🎟 *Ticket:* 4 USDT (TRC20)\n🎁 *Win:* Up to 20,000 USDT Daily\n🔗 *Draw Time:* 12:01 AM IST Daily\n💸 *Referral:* Earn 1 USDT per ticket forever\n\n✔ 100% Blockchain. No Scam."
            ), parse_mode='Markdown')

    elif data == 'referral_info':
        await query.edit_message_text(
            text=(
                "💸 *Lifetime Referral Program*\n\n"
                "- Refer once, earn forever!\n"
                "- Get *1 USDT per ticket* from your referrals\n"
                "- Instant smart contract payments\n"
                "\n👥 Refer more, earn more. Unlimited potential."
            ), parse_mode='Markdown')

# --- /winners Command ---
async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🏆 *Past Winners:*\n\n"
    for user, amount, date in past_winners:
        msg += f"{date} — {user} won {amount}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- Admin Broadcast (Optional) ---
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    message = ' '.join(context.args)
    if not message:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return
    for user_id in context.bot_data.get("subscribers", []):
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
        except:
            continue

# --- Save New Users ---
async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.bot_data.setdefault("subscribers", set()).add(user_id)

# --- Main Bot Function ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("winners", winners))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("save", save_user))

    # Run bot
    application.run_polling()

if __name__ == '__main__':
    main()
