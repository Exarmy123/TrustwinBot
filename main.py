import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from datetime import datetime, time, timedelta
import asyncio
import random
from dotenv import load_dotenv

load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Your Telegram user id (int)
USDT_WALLET = os.getenv("USDT_WALLET")  # Your TRC-20 USDT Wallet address

# In-memory databases (replace with real DB in production)
users = {}          # user_id : { 'tickets': [], 'referrals': [], 'referrer': user_id or None }
tickets = []        # list of tuples (user_id, ticket_number)
referral_commissions = {}  # user_id : total_commission_amount

# Config
TICKET_PRICE_USDT = 1  # 1 USDT per ticket

WELCOME_MESSAGE = """
Welcome to TrustWin Lottery Bot! 🎉

🎟️ Buy lottery tickets at 1 USDT each.
👫 Refer friends and earn 50% commission on their ticket purchases FOR LIFE!
🏆 Daily draw at 12:01 AM IST. Winner gets all the pot!
💰 Instant USDT payouts on wins and referrals.

Use /buy to purchase tickets.
Use /mytickets to see your tickets.
Use /referral to get your referral link.
"""

# Utility functions
def generate_ticket_number():
    # 6-digit ticket number
    return random.randint(100000, 999999)

def get_referral_link(user_id):
    return f"https://t.me/YourBotUsername?start=ref{user_id}"

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # Check if user started with referral
    referrer_id = None
    if args and args[0].startswith("ref"):
        try:
            referrer_id = int(args[0][3:])
            if referrer_id == user.id:
                referrer_id = None  # Can't refer self
        except:
            referrer_id = None

    if user.id not in users:
        users[user.id] = {"tickets": [], "referrals": [], "referrer": referrer_id}
        # Add to referrer's referral list
        if referrer_id and referrer_id in users:
            users[referrer_id]["referrals"].append(user.id)
    
    await update.message.reply_text(WELCOME_MESSAGE)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        await update.message.reply_text("Please start the bot first by sending /start")
        return

    # Simple prompt to enter number of tickets
    await update.message.reply_text("How many tickets do you want to buy? Send a number (e.g., 3). Each ticket costs 1 USDT.")

    # Next message will be handled by message handler

async def buy_ticket_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Please send a valid number (e.g., 2).")
        return

    count = int(text)
    if count < 1 or count > 10:
        await update.message.reply_text("You can buy minimum 1 and maximum 10 tickets at a time.")
        return

    total_cost = count * TICKET_PRICE_USDT

    # Here you would integrate payment gateway or manual payment verification.
    # For now, assume payment is done manually outside the bot.

    # Generate tickets
    new_tickets = []
    for _ in range(count):
        ticket_num = generate_ticket_number()
        new_tickets.append(ticket_num)
        tickets.append((user_id, ticket_num))
        users[user_id]["tickets"].append(ticket_num)

    # Calculate referral commission if any
    referrer_id = users[user_id]["referrer"]
    if referrer_id:
        commission = total_cost * 0.5  # 50% commission
        referral_commissions[referrer_id] = referral_commissions.get(referrer_id, 0) + commission
        # Ideally, send commission instantly here if wallet integration is done.

    await update.message.reply_text(
        f"Congrats! You bought {count} ticket(s): {', '.join(str(t) for t in new_tickets)}\n"
        f"Total cost: {total_cost} USDT\n"
        f"Refer friends and earn 50% commission on their purchases!\n"
        f"Use /referral to get your referral link."
    )

async def mytickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or not users[user_id]["tickets"]:
        await update.message.reply_text("You don't have any tickets yet. Use /buy to purchase tickets.")
        return
    user_tickets = users[user_id]["tickets"]
    await update.message.reply_text(f"Your tickets: {', '.join(str(t) for t in user_tickets)}")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = get_referral_link(user_id)
    await update.message.reply_text(f"Share this referral link to earn 50% commission for life:\n{link}")

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    total_users = len(users)
    total_tickets = len(tickets)
    total_commissions = sum(referral_commissions.values())
    await update.message.reply_text(
        f"📊 Admin Status:\n"
        f"Total Users: {total_users}\n"
        f"Total Tickets Sold: {total_tickets}\n"
        f"Total Referral Commissions: {total_commissions:.2f} USDT"
    )

# Daily draw function (run in background)
async def daily_draw(app):
    while True:
        now = datetime.now()
        # Draw at 12:01 AM IST => UTC+5:30 means 18:31 UTC previous day
        # Let's run draw at UTC 18:31 daily
        target_time_utc = datetime.combine(now.date(), time(18, 31))
        if now > target_time_utc:
            target_time_utc += timedelta(days=1)
        wait_seconds = (target_time_utc - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        if not tickets:
            logger.info("No tickets sold today, no draw.")
            continue

        # Pick a winner randomly
        winner_ticket = random.choice(tickets)
        winner_user_id = winner_ticket[0]

        # Total pot is total tickets * ticket price
        total_pot = len(tickets) * TICKET_PRICE_USDT

        # TODO: Send USDT payout to winner's wallet here

        # Notify winner and admin
        try:
            await app.bot.send_message(
                chat_id=winner_user_id,
                text=f"🎉 Congratulations! You won today's lottery with ticket #{winner_ticket[1]}!\nYou have won {total_pot} USDT! 🏆"
            )
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🏆 Daily Lottery Winner: User {winner_user_id} with ticket #{winner_ticket[1]} won {total_pot} USDT."
            )
        except Exception as e:
            logger.error(f"Error sending winner notification: {e}")

        # Reset tickets for next day
        tickets.clear()
        for u in users.values():
            u["tickets"].clear()

# Unknown command handler
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sorry, I didn't understand that command. Use /help to see available commands.")

# Main function to run the bot
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("mytickets", mytickets))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("adminstatus", admin_status))

    # Message handler for number of tickets after /buy
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), buy_ticket_number))

    app.add_handler(MessageHandler(filters.COMMAND, unknown))  # Unknown commands

    # Run daily draw in background
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(daily_draw(app)), interval=86400, first=10)

    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
