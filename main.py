import os
import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext
)
from datetime import datetime, timedelta
import asyncio
import random
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY")

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory database (to be replaced with Supabase integration)
users = {}
tickets = []
referral_commissions = {}
payment_requests = {}
TICKET_PRICE_USDT = 1

WELCOME_MESSAGE = f"""
Welcome to TrustWin Lottery Bot! 🎉

🎟️ Buy lottery tickets at 1 USDT each.
🤟 Refer friends and earn 50% commission on their ticket purchases FOR LIFE!
🏆 Daily draw at 12:01 AM IST. Winner gets all the pot!
💰 Instant USDT payouts on wins and referrals.

Choose an option below to get started:
"""

HOW_FUNDS_ALLOCATED = """
💸 How Your 4 USDT is Allocated:

🏆 Daily Prize Pool: 2.00 USDT - Awarded instantly to the daily winner
🤝 Referral Commission: 1.00 USDT - Paid directly to the referring user
🛡️ Global System Tax: 1.00 USDT - For marketing, upgrades, global expansion, and security
"""

def generate_ticket_number():
    return random.randint(100000, 999999)

def get_referral_link(user_id):
    return f"https://t.me/TrustWinBot?start=ref{user_id}"

def send_main_menu(update: Update):
    keyboard = [[
        KeyboardButton("Start"),
        KeyboardButton("My Referral")
    ], [
        KeyboardButton("Buy Ticket"),
        KeyboardButton("Check Result")
    ], [
        KeyboardButton("How It Works"),
        KeyboardButton("My Tickets")
    ], [
        KeyboardButton("Withdraw"),
        KeyboardButton("Support")
    ], [
        KeyboardButton("Leaderboard")
    ]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(WELCOME_MESSAGE, reply_markup=reply_markup)

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    args = context.args
    referrer_id = None
    if args and args[0].startswith("ref"):
        try:
            referrer_id = int(args[0][3:])
            if referrer_id == user.id:
                referrer_id = None
        except:
            referrer_id = None

    if user.id not in users:
        users[user.id] = {"tickets": [], "referrals": [], "referrer": referrer_id}
        if referrer_id and referrer_id in users:
            users[referrer_id]["referrals"].append(user.id)

    send_main_menu(update)

def handle_text(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text == "start":
        start(update, context)
    elif text == "my referral":
        referral(update, context)
    elif text == "buy ticket":
        buy(update, context)
    elif text == "check result":
        context.bot.send_message(update.effective_chat.id, "Daily draw happens at 12:01 AM IST. Stay tuned!")
    elif text == "how it works":
        update.message.reply_text(WELCOME_MESSAGE + "\n" + HOW_FUNDS_ALLOCATED)
    elif text == "my tickets":
        mytickets(update, context)
    elif text == "withdraw":
        get_usdt(update, context)
    elif text == "support":
        update.message.reply_text("For support, contact @TrustWinSupport")
    elif text == "leaderboard":
        top_referrers = sorted(referral_commissions.items(), key=lambda x: x[1], reverse=True)[:5]
        msg = "🏆 Leaderboard - Top Referrers:\n"
        for i, (uid, amount) in enumerate(top_referrers, 1):
            msg += f"{i}. User {uid} - {amount:.2f} USDT\n"
        update.message.reply_text(msg or "No referrals yet.")
    elif text.startswith("send:") and update.effective_user.id == ADMIN_ID:
        parts = text[5:].split("|", 1)
        if len(parts) == 2:
            target, msg = parts
            if target.strip().lower() == "all":
                for uid in users:
                    try:
                        context.bot.send_message(uid, msg.strip())
                    except:
                        continue
                update.message.reply_text("✅ Message sent to all users.")
            else:
                try:
                    context.bot.send_message(int(target.strip()), msg.strip())
                    update.message.reply_text("✅ Message sent to user.")
                except:
                    update.message.reply_text("❌ Failed to send message.")
    elif text.isdigit():
        buy_ticket_number(update, context)
    else:
        update.message.reply_text("Invalid option. Please use the menu.")

def buy(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users:
        update.message.reply_text("Please start the bot first using /start")
        return
    update.message.reply_text("How many tickets do you want to buy? Send a number (1-10). Each costs 1 USDT. After sending number, you will receive payment address.")

def buy_ticket_number(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        update.message.reply_text("Please send a valid number.")
        return
    count = int(text)
    if not (1 <= count <= 10):
        update.message.reply_text("Buy minimum 1 and maximum 10 tickets.")
        return

    total_cost = count * TICKET_PRICE_USDT
    update.message.reply_text(f"To buy {count} ticket(s), please send exactly {total_cost} USDT (only TRC20 network) to the address below:")
    update.message.reply_text(f"Send USDT (TRC20) to:\n{USDT_ADDRESS}")
    update.message.reply_text("Please also provide your USDT TRC20 address to receive winnings and referral commission.\n\nOnce your payment is confirmed, tickets will be added. If not updated in 10 minutes, contact @TrustWinSupport with transaction details.")

def mytickets(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users or not users[user_id]["tickets"]:
        update.message.reply_text("You have no tickets. Use 'Buy Ticket' to get some.")
        return
    update.message.reply_text(f"Your tickets: {', '.join(map(str, users[user_id]['tickets']))}")

def referral(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(f"Your referral link:\n{get_referral_link(user_id)}")

def get_usdt(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users:
        update.message.reply_text("Please start the bot first using /start")
        return

    if referral_commissions.get(user_id, 0) <= 0:
        update.message.reply_text("You have no referral commissions to claim yet.")
        return

    if user_id in payment_requests:
        update.message.reply_text("You've already requested a USDT payout. Please wait until it is processed.")
        return

    amount = referral_commissions[user_id]
    payment_requests[user_id] = amount
    referral_commissions[user_id] = 0
    update.message.reply_text(f"✅ Your USDT {amount:.2f} payout request has been sent to admin. You will receive payment shortly.")
    context.bot.send_message(ADMIN_ID, f"💸 Payout Request: User {user_id} requested {amount:.2f} USDT referral commission.")

def daily_draw(context: CallbackContext):
    now = datetime.utcnow()
    ist_time = now + timedelta(hours=5, minutes=30)
    if ist_time.hour == 0 and ist_time.minute == 1:
        if not tickets:
            logger.info("No tickets, skipping draw.")
            return

        winner = random.choice(tickets)
        winner_id, winner_ticket = winner
        pot = len(tickets) * TICKET_PRICE_USDT
        try:
            context.bot.send_message(winner_id, f"🎉 You won the lottery! Ticket #{winner_ticket}. Amount: {pot} USDT.")
            context.bot.send_message(ADMIN_ID, f"🏆 Winner: User {winner_id} | Ticket #{winner_ticket} | Prize: {pot} USDT")
        except Exception as e:
            logger.error(f"Notification failed: {e}")

        tickets.clear()
        for u in users.values():
            u["tickets"] = []

def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    job_queue = updater.job_queue
    job_queue.run_repeating(daily_draw, interval=60, first=0)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
