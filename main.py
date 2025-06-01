import os
import logging
from telegram import Update
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

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USDT_WALLET = os.getenv("USDT_WALLET")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory database
users = {}
tickets = []
referral_commissions = {}
payment_requests = {}
TICKET_PRICE_USDT = 1

WELCOME_MESSAGE = f"""
Welcome to TrustWin Lottery Bot! 🎉

🎟️ Buy lottery tickets at 4 USDT each.
🤟 Refer friends and earn 25% commission on their ticket purchases FOR LIFE!
🏆 Daily draw at 12:01 AM IST. Winner gets all the pot!
💰 Instant USDT payouts on wins and referrals.

Use /buy to purchase tickets.
Use /mytickets to see your tickets.
Use /referral to get your referral link.
"""

def generate_ticket_number():
    return random.randint(100000, 999999)

def get_referral_link(user_id):
    return f"https://t.me/TrustWinBot?start=ref{user_id}"

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    args = context.args
    referrer_id = None
    if args and args[0].startswith("ref"):
        try:
            rTrueferrer_id = int(args[0][3:])
            if referrer_id == user.id:
                referrer_id = None
        except:
            referrer_id = None

    if user.id not in users:
        users[user.id] = {"tickets": [], "referrals": [], "referrer": referrer_id}
        if referrer_id and referrer_id in users:
            users[referrer_id]["referrals"].append(user.id)
    update.message.reply_text(WELCOME_MESSAGE)

def buy(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users:
        update.message.reply_text("Please start the bot first using /start")
        return
    update.message.reply_text("How many tickets do you want to buy? Send a number (1-10). Each costs 1 USDT.")

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
    new_tickets = []
    for _ in range(count):
        t = generate_ticket_number()
        tickets.append((user_id, t))
        users[user_id]["tickets"].append(t)
        new_tickets.append(t)

    referrer = users[user_id]["referrer"]
    if referrer:
        commission = total_cost * 0.5
        referral_commissions[referrer] = referral_commissions.get(referrer, 0) + commission

    update.message.reply_text(
        f"Congrats! You bought {count} ticket(s): {', '.join(map(str, new_tickets))}\n"
        f"Total cost: {total_cost} USDT\nUse /referral to get your referral link."
    )

def mytickets(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in users or not users[user_id]["tickets"]:
        update.message.reply_text("You have no tickets. Use /buy to get some.")
        return
    update.message.reply_text(f"Your tickets: {', '.join(map(str, users[user_id]['tickets']))}")

def referral(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(f"Your referral link:\n{get_referral_link(user_id)}")

def admin_status(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    update.message.reply_text(
        f"📊 Admin Status:\nUsers: {len(users)}\nTickets Sold: {len(tickets)}\nTotal Referral Commissions: {sum(referral_commissions.values()):.2f} USDT"
    )

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
    update.message.reply_text(f"✅ Your USDT {amount:.2f} payout request has been sent to admin. You will receive payment shortly.")
    context.bot.send_message(ADMIN_ID, f"💸 Payout Request: User {user_id} requested {amount:.2f} USDT referral commission.")

def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("Unknown command. Use /buy, /mytickets, /referral.")

def getwinner(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    if not tickets:
        update.message.reply_text("No tickets have been sold today.")
        return

    winner = random.choice(tickets)
    winner_id, winner_ticket = winner
    pot = len(tickets) * TICKET_PRICE_USDT

    context.bot.send_message(winner_id, f"🎉 You won the lottery! Ticket #{winner_ticket}. Amount: {pot} USDT.")
    update.message.reply_text(f"🏆 Winner: User {winner_id} | Ticket #{winner_ticket} | Prize: {pot} USDT")

    tickets.clear()
    for u in users.values():
        u["tickets"] = []

def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("buy", buy))
    dp.add_handler(CommandHandler("mytickets", mytickets))
    dp.add_handler(CommandHandler("referral", referral))
    dp.add_handler(CommandHandler("adminstatus", admin_status))
    dp.add_handler(CommandHandler("getwinner", getwinner))
    dp.add_handler(CommandHandler("getusdt", get_usdt))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, buy_ticket_number))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    job_queue = updater.job_queue
    job_queue.run_repeating(daily_draw, interval=60, first=0)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
