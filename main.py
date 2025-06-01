import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
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
TICKET_PRICE_USDT = 1

WELCOME_MESSAGE = f"""
Welcome to TrustWin Lottery Bot! 🎉

🎟️ Buy lottery tickets at 4 USDT each.
👫 Refer friends and earn 25% commission on their ticket purchases FOR LIFE!
🏆 Daily draw at 12:01 AM IST. Winner gets all the pot!
💰 Instant USDT payouts on wins and referrals.

Use /buy to purchase tickets.
Use /mytickets to see your tickets.
Use /referral to get your referral link.
"""

def generate_ticket_number():
    return random.randint(100000, 999999)

def get_referral_link(user_id):
    return f"https://t.me/YourBotUsername?start=ref{user_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(WELCOME_MESSAGE)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        await update.message.reply_text("Please start the bot first using /start")
        return
    await update.message.reply_text("How many tickets do you want to buy? Send a number (1-10). Each costs 1 USDT.")

async def buy_ticket_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Please send a valid number.")
        return
    count = int(text)
    if not (1 <= count <= 10):
        await update.message.reply_text("Buy minimum 1 and maximum 10 tickets.")
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

    await update.message.reply_text(
        f"Congrats! You bought {count} ticket(s): {', '.join(map(str, new_tickets))}\n"
        f"Total cost: {total_cost} USDT\nUse /referral to get your referral link."
    )

async def mytickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or not users[user_id]["tickets"]:
        await update.message.reply_text("You have no tickets. Use /buy to get some.")
        return
    await update.message.reply_text(f"Your tickets: {', '.join(map(str, users[user_id]['tickets']))}")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your referral link:\n{get_referral_link(user_id)}")

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        f"\U0001F4CA Admin Status:\nUsers: {len(users)}\nTickets Sold: {len(tickets)}\nTotal Referral Commissions: {sum(referral_commissions.values()):.2f} USDT"
    )

async def daily_draw(context: ContextTypes.DEFAULT_TYPE):
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
            await context.bot.send_message(winner_id, f"🎉 You won the lottery! Ticket #{winner_ticket}. Amount: {pot} USDT.")
            await context.bot.send_message(ADMIN_ID, f"🏆 Winner: User {winner_id} | Ticket #{winner_ticket} | Prize: {pot} USDT")
        except Exception as e:
            logger.error(f"Notification failed: {e}")

        tickets.clear()
        for u in users.values():
            u["tickets"] = []

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /buy, /mytickets, /referral.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("mytickets", mytickets))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("adminstatus", admin_status))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), buy_ticket_number))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.job_queue.run_repeating(daily_draw, interval=60, first=0)

    app.run_polling()

if __name__ == "__main__":
    main()
