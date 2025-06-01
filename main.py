import os
import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from datetime import datetime, timedelta
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

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory data structures
users = {}
tickets = []
referral_commissions = {}
payment_requests = {}
TICKET_PRICE_USDT = 4

WELCOME_MESSAGE = f"""
Welcome to TrustWin Lottery Bot! 🎉

🎟️ Buy lottery tickets at {TICKET_PRICE_USDT} USDT each.
🤟 Refer friends ONCE and earn 25% lifetime passive income on their ticket purchases!
🏆 Daily draw at 12:01 AM IST. Winner gets 100% of the total ticket sale prize pool!
💰 Instant USDT payouts on wins and referrals.

Choose an option below to get started:
"""

HOW_FUNDS_ALLOCATED = f"""
💸 How Your {TICKET_PRICE_USDT} USDT is Allocated:

🏆 Daily Prize Pool: 2.00 USDT - Goes to the winner
🤝 Referral Commission: 1.00 USDT - Lifetime commission to referrer
🛡️ Global System Tax: 1.00 USDT - For marketing, development, and platform operations
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

    send_main_menu(update)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text == "start":
        await start(update, context)
    elif text == "my referral":
        await referral(update, context)
    elif text == "buy ticket":
        await buy(update, context)
    elif text == "check result":
        await context.bot.send_message(update.effective_chat.id, "Daily draw happens at 12:01 AM IST. Stay tuned!")
    elif text == "how it works":
        await update.message.reply_text(WELCOME_MESSAGE + "\n" + HOW_FUNDS_ALLOCATED)
    elif text == "my tickets":
        await mytickets(update, context)
    elif text == "withdraw":
        await get_usdt(update, context)
    elif text == "support":
        await update.message.reply_text("For support, contact @TrustWinSupport")
    elif text == "leaderboard":
        top_referrers = sorted(referral_commissions.items(), key=lambda x: x[1], reverse=True)[:5]
        msg = "🏆 Leaderboard - Top Referrers:\n"
        for i, (uid, amount) in enumerate(top_referrers, 1):
            msg += f"{i}. User {uid} - {amount:.2f} USDT\n"
        await update.message.reply_text(msg or "No referrals yet.")
    elif text.startswith("send:") and update.effective_user.id == ADMIN_ID:
        parts = text[5:].split("|", 1)
        if len(parts) == 2:
            target, msg = parts
            if target.strip().lower() == "all":
                for uid in users:
                    try:
                        await context.bot.send_message(uid, msg.strip())
                    except:
                        continue
                await update.message.reply_text("✅ Message sent to all users.")
            else:
                try:
                    await context.bot.send_message(int(target.strip()), msg.strip())
                    await update.message.reply_text("✅ Message sent to user.")
                except:
                    await update.message.reply_text("❌ Failed to send message.")
    elif text.isdigit():
        await buy_ticket_number(update, context)
    else:
        await update.message.reply_text("Invalid option. Please use the menu.")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        await update.message.reply_text("Please start the bot first using /start")
        return
    await update.message.reply_text(f"How many tickets do you want to buy? Send a number (1-10). Each costs {TICKET_PRICE_USDT} USDT. After sending number, you will receive payment address.")

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
    for _ in range(count):
        ticket_number = generate_ticket_number()
        tickets.append((user_id, ticket_number))
        users[user_id]["tickets"].append(ticket_number)

    await update.message.reply_text(f"To buy {count} ticket(s), please send exactly {total_cost} USDT (only TRC20 network) to the address below:")
    await update.message.reply_text(f"Send USDT (TRC20) to:\n{USDT_ADDRESS}")
    await update.message.reply_text("Please also provide your USDT TRC20 address to receive winnings and referral commission.\n\nOnce your payment is confirmed, tickets will be added. If not updated in 10 minutes, contact @TrustWinSupport with transaction details.")

    # Referral commission
    referrer_id = users[user_id].get("referrer")
    if referrer_id:
        commission = count * 1.0
        referral_commissions[referrer_id] = referral_commissions.get(referrer_id, 0) + commission

async def mytickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or not users[user_id]["tickets"]:
        await update.message.reply_text("You have no tickets. Use 'Buy Ticket' to get some.")
        return
    await update.message.reply_text(f"Your tickets: {', '.join(map(str, users[user_id]['tickets']))}")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your referral link:\n{get_referral_link(user_id)}")

async def get_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        await update.message.reply_text("Please start the bot first using /start")
        return

    if referral_commissions.get(user_id, 0) <= 0:
        await update.message.reply_text("You have no referral commissions to claim yet.")
        return

    if user_id in payment_requests:
        await update.message.reply_text("You've already requested a USDT payout. Please wait until it is processed.")
        return

    amount = referral_commissions[user_id]
    payment_requests[user_id] = amount
    referral_commissions[user_id] = 0
    await update.message.reply_text(f"✅ Your USDT {amount:.2f} payout request has been sent to admin. You will receive payment shortly.")
    await context.bot.send_message(ADMIN_ID, f"💸 Payout Request: User {user_id} requested {amount:.2f} USDT referral commission.")

async def daily_draw(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    ist_time = now + timedelta(hours=5, minutes=30)
    if ist_time.hour == 0 and ist_time.minute == 1:
        if not tickets:
            logger.info("No tickets, skipping draw.")
            return

        winner = random.choice(tickets)
        winner_id, winner_ticket = winner
        pot = len(tickets) * 2
        try:
            await context.bot.send_message(winner_id, f"🎉 You won the lottery! Ticket #{winner_ticket}. Amount: {pot} USDT.")
            await context.bot.send_message(ADMIN_ID, f"🏆 Winner: User {winner_id} | Ticket #{winner_ticket} | Prize: {pot} USDT")
        except Exception as e:
            logger.error(f"Notification failed: {e}")

        tickets.clear()
        for u in users.values():
            u["tickets"] = []

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    job_queue = app.job_queue
    job_queue.run_repeating(daily_draw, interval=60)

    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
