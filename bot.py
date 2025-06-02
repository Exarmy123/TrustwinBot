# bot.py

import os
import logging
import asyncio
import random
import datetime
from decimal import Decimal

# Uncomment the next line if using a .env file locally
# from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder
from telegram.constants import ParseMode

from supabase.client import create_client, Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# --- Environment Variables ---
# Uncomment next line if using a .env file
# load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) # Ensure this is an integer
USDT_WALLET = os.getenv("USDT_WALLET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TICKET_PRICE_USDT = Decimal(os.getenv("TICKET_PRICE_USDT", "1.0"))
REFERRAL_PERCENT = Decimal(os.getenv("REFERRAL_PERCENT", "0.5")) # 0.5 for 50%
WINNER_AMOUNT_USDT = Decimal(os.getenv("WINNER_AMOUNT_USDT", "5.0"))
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Kolkata") # Default to IST

if not all([BOT_TOKEN, ADMIN_ID, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY]):
    logging.error("Missing required environment variables!")
    exit(1)

# --- Supabase Client ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Global State (for pending payments - Simple in-memory approach) ---
# In a multi-instance setup, this should be persistent (e.g., Redis or DB)
pending_payments = {} # {user_id: {amount: Decimal, message_id: int, date: date}}

# --- Helper Functions: Database ---

async def get_user(telegram_id: int):
    """Fetch a user from the database by telegram_id."""
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).single().execute()
        if response.data:
            return response.data
        return None
    except Exception as e:
        logger.error(f"Supabase error fetching user {telegram_id}: {e}")
        return None

async def create_user(telegram_id: int, username: str | None, first_name: str | None, last_name: str | None, referrer_telegram_id: int | None = None):
    """Create a new user in the database."""
    try:
        data_to_insert = {
            'telegram_id': telegram_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'referrer_telegram_id': referrer_telegram_id,
            'join_date': datetime.datetime.now(pytz.timezone(TIMEZONE_STR)).isoformat() # Store in timezone aware format
        }
        response = supabase.from_('users').insert([data_to_insert]).execute()
        if response.data:
            logger.info(f"New user created: {telegram_id} (Referrer: {referrer_telegram_id})")
            return response.data[0]
        logger.error(f"Supabase error creating user {telegram_id}: {response.error}")
        return None
    except Exception as e:
        logger.error(f"Supabase error creating user {telegram_id}: {e}")
        return None

async def increment_daily_tickets(telegram_id: int, count: int = 1):
    """Increment ticket count for a user for today's date."""
    try:
        today = datetime.date.today()
        # Use the SQL function defined in Supabase
        response = supabase.rpc('increment_daily_ticket', {'user_id': telegram_id, 'ticket_date': today}).execute()
        if response.error:
             logger.error(f"Supabase error incrementing tickets for {telegram_id} on {today}: {response.error}")
             return False
        logger.info(f"Tickets incremented for user {telegram_id} for {today}. Count: {count}") # The function always increments by 1
        return True
    except Exception as e:
        logger.error(f"Supabase error incrementing tickets for {telegram_id}: {e}")
        return False

async def get_daily_ticket_counts(date: datetime.date):
    """Get aggregated ticket counts for a specific date."""
    try:
        response = supabase.from_('daily_tickets').select('telegram_id, count').eq('date', date.isoformat()).execute()
        if response.data:
            return response.data
        return []
    except Exception as e:
        logger.error(f"Supabase error fetching daily tickets for {date}: {e}")
        return []

async def add_winner(telegram_id: int, amount: Decimal, win_date: datetime.date):
    """Add a winner entry to the database."""
    try:
        data_to_insert = {
            'telegram_id': telegram_id,
            'amount': float(amount), # Supabase stores numeric as float by default
            'win_date': win_date.isoformat()
        }
        response = supabase.from_('winners').insert([data_to_insert]).execute()
        if response.data:
            logger.info(f"Winner recorded: {telegram_id} on {win_date} with {amount} USDT")
            return response.data[0]
        logger.error(f"Supabase error adding winner {telegram_id}: {response.error}")
        return None
    except Exception as e:
        logger.error(f"Supabase error adding winner {telegram_id}: {e}")
        return None

async def get_latest_winners(limit: int):
    """Fetch the latest winners from the database."""
    try:
        response = supabase.from_('winners').select('telegram_id, amount, win_date').order('win_date', desc=True).limit(limit).execute()
        if response.data:
            # Fetch user details for winners
            winner_telegram_ids = [w['telegram_id'] for w in response.data]
            if winner_telegram_ids:
                user_response = supabase.from_('users').select('telegram_id, username, first_name, last_name').in_('telegram_id', winner_telegram_ids).execute()
                user_map = {user['telegram_id']: user for user in user_response.data} if user_response.data else {}
                for winner in response.data:
                    winner['user_info'] = user_map.get(winner['telegram_id'])
            return response.data
        return []
    except Exception as e:
        logger.error(f"Supabase error fetching latest winners: {e}")
        return []

async def get_all_user_telegram_ids():
    """Fetch all user telegram_ids for broadcasting."""
    try:
        response = supabase.from_('users').select('telegram_id').execute()
        if response.data:
            return [user['telegram_id'] for user in response.data]
        return []
    except Exception as e:
        logger.error(f"Supabase error fetching all user telegram_ids: {e}")
        return []

async def get_total_users():
    """Get the total count of users."""
    try:
        response = supabase.from_('users').select('count', count='exact').execute()
        return response.count if response.count is not None else 0
    except Exception as e:
        logger.error(f"Supabase error fetching total users: {e}")
        return 0

async def get_todays_total_tickets():
    """Get the total ticket count for today."""
    try:
        today = datetime.date.today()
        response = supabase.from_('daily_tickets').select('count', sum='count').eq('date', today.isoformat()).execute()
        # Supabase sum returns a list of dicts, e.g., [{'sum': 10}]
        if response.data and response.data[0] and response.data[0]['sum'] is not None:
             return int(response.data[0]['sum'])
        return 0
    except Exception as e:
        logger.error(f"Supabase error fetching today's total tickets: {e}")
        return 0

async def get_random_marketing_message():
    """Fetch a random marketing message from the database."""
    try:
        # This is a simple approach. For many messages, might need pagination and random index
        response = supabase.from_('messages').select('content').eq('type', 'marketing').execute()
        if response.data:
            messages = [msg['content'] for msg in response.data]
            return random.choice(messages) if messages else None
        return None
    except Exception as e:
        logger.error(f"Supabase error fetching marketing message: {e}")
        return None

# --- Helper Functions: USDT Simulation ---

async def simulate_send_usdt(recipient_info: str, amount: Decimal, transaction_type: str):
    """
    Simulates sending USDT.
    In a real application, this would interact with a blockchain API (e.g., TronGrid).
    Recipient info could be a wallet address or internal user identifier.
    """
    logger.info(f"SIMULATING USDT SEND: Type='{transaction_type}', Recipient='{recipient_info}', Amount='{amount:.2f} USDT'")
    # Simulate network delay
    await asyncio.sleep(1)
    logger.info(f"SIMULATION COMPLETE: USDT sent successfully (simulated).")
    return True # Assume success for simulation

# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command, registers user and provides referral info."""
    user = update.effective_user
    telegram_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name

    referrer_telegram_id = None
    if context.args:
        try:
            potential_referrer_id = int(context.args[0])
            # Check if the potential referrer exists and is not the user themselves
            if potential_referrer_id != telegram_id:
                referrer_user = await get_user(potential_referrer_id)
                if referrer_user:
                    referrer_telegram_id = potential_referrer_id
                    logger.info(f"User {telegram_id} started with referrer {referrer_telegram_id}")
                else:
                    logger.warning(f"User {telegram_id} used invalid referrer ID: {context.args[0]}")
            else:
                 logger.warning(f"User {telegram_id} tried to refer themselves.")
        except ValueError:
            logger.warning(f"User {telegram_id} used invalid referral link format: {context.args[0]}")

    db_user = await get_user(telegram_id)

    welcome_message = (
        f"Hello {user.first_name}! Welcome to TrustWin Bot! \n\n" # Removed 🎉
        "Get your tickets daily for a chance to win big in our USDT lottery!\n\n"
    )

    if db_user is None:
        await create_user(telegram_id, username, first_name, last_name, referrer_telegram_id)
        welcome_message += (
            "You've been registered! Thanks for joining.\n"
        )

        if referrer_telegram_id:
            # Notify referrer about new referral - this happens on join
            # Actual reward is on ticket purchase
            try:
                await context.bot.send_message(
                    chat_id=referrer_telegram_id,
                    text=f"Great news! Your referral {user.first_name} (@{username or 'N/A'}) has joined TrustWin Bot using your link!\n" # Removed ✨
                         "You'll earn 50% of the ticket price every time they buy a ticket!"
                )
                logger.info(f"Notified referrer {referrer_telegram_id} about new user {telegram_id}")
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_telegram_id}: {e}")


    welcome_message += (
        f"The prize amount for today's draw is *{WINNER_AMOUNT_USDT:.2f} USDT*.\n"
        f"Each ticket costs *{TICKET_PRICE_USDT:.2f} USDT*.\n\n"
        "Use the /buy command to get your ticket(s)!\n\n"
        f"Want to earn passively? Share your unique referral link:\n"
        f"`https://t.me/{context.bot.username}?start={telegram_id}`\n"
        f"You get {REFERRAL_PERCENT*100:.0f}% of the ticket price for every ticket your referred friends buy, FOREVER!\n\n"
        "May the odds be ever in your favor! " # Removed 🍀
    )

    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /buy command to initiate ticket purchase."""
    user = update.effective_user
    telegram_id = user.id

    # Ensure user exists in DB before allowing purchase flow
    db_user = await get_user(telegram_id)
    if not db_user:
        await update.message.reply_text("Please use the /start command first to register.")
        return

    # Ask the user how many tickets they want to buy (optional, simple version assumes 1)
    # For this version, let's assume buying 1 ticket per confirmation.
    # If they send /buy multiple times, it initiates multiple payments.
    # A more complex version would ask for quantity or handle multiple confirmations.

    ticket_amount = TICKET_PRICE_USDT # Assuming 1 ticket per purchase flow

    keyboard = [
        [InlineKeyboardButton("I have paid", callback_data=f"paid_{ticket_amount}")] # Removed ✅
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        f"To buy one ticket for *{ticket_amount:.2f} USDT*:\n\n"
        f"1. Send exactly *{ticket_amount:.2f} USDT (TRC-20)* to the following wallet address:\n"
        f"`{USDT_WALLET}`\n\n"
        "2. After sending, click the 'I have paid' button below.\n\n" # Removed ✅
        "Your ticket(s) will be counted for today's draw after admin verification. Good luck! " # Removed 🍀
    )

    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def paid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'I have paid' button click."""
    query = update.callback_query
    user = query.effective_user
    telegram_id = user.id
    data = query.data # Format: paid_AMOUNT

    await query.answer("Processing your payment confirmation...")

    try:
        amount_str = data.split('_')[1]
        claimed_amount = Decimal(amount_str)
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid payment confirmation data.")
        logger.error(f"Invalid callback data received: {data}")
        return

    # --- Admin Verification Flow ---
    # Store the pending payment information
    pending_payments[telegram_id] = {
        'amount': claimed_amount,
        'date': datetime.date.today(),
        'message_id': query.message.message_id # Store message ID to edit later
    }

    # Notify admin
    admin_notification_text = (
        f"Payment Claimed! \n\n" # Removed 🚨 🚨
        f"User: {user.first_name} (@{user.username or 'N/A'}) [ID: `{telegram_id}`]\n"
        f"Claimed Amount: *{claimed_amount:.2f} USDT*\n"
        f"Claim Date: {datetime.date.today().isoformat()}\n\n"
        f"Check payment and use `/confirm_payment {telegram_id}` if verified."
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_notification_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Admin notified about pending payment from {telegram_id}")
        await query.edit_message_text(
            f"Received your payment confirmation for {claimed_amount:.2f} USDT.\n" # Removed ✅
            "Please wait while the admin verifies the transaction. Your tickets will be added shortly!"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin {ADMIN_ID} about payment claim: {e}")
        await query.edit_message_text(
            f"Received your payment confirmation for {claimed_amount:.2f} USDT.\n" # Removed ✅
            "There was an issue notifying the admin, but your claim is recorded. Please wait for verification."
        )

# --- Admin Commands ---

async def is_admin(update: Update) -> bool:
    """Checks if the user is the admin."""
    return update.effective_user.id == ADMIN_ID

async def admin_only(handler):
    """Decorator to restrict handlers to admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await is_admin(update):
            await update.message.reply_text("You are not authorized to use this command.") # Removed 🔒
            return
        await handler(update, context)
    return wrapper

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to show bot statistics."""
    total_users = await get_total_users()
    todays_tickets = await get_todays_total_tickets()
    pending_count = len(pending_payments)

    stats_text = (
        "Bot Statistics \n\n" # Removed 📊 📊
        f"Total Users: `{total_users}`\n"
        f"Today's Tickets: `{todays_tickets}`\n"
        f"Pending Payments (Admin Verification): `{pending_count}`"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list active users."""
    all_users = await get_all_user_telegram_ids()

    if not all_users:
        await update.message.reply_text("No users found.")
        return

    user_list_text = "Active Users \n\n" # Removed 👥 👥
    # For brevity, list only a few or summarize
    if len(all_users) > 50:
        user_list_text += f"Listing first 50 of {len(all_users)} users:\n"
        all_users = all_users[:50]

    # Fetch details for these users to show username/name
    user_details_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', all_users).execute()
    user_details = user_details_response.data if user_details_response.data else []

    for user in user_details:
        name = user.get('first_name', 'N/A')
        username = user.get('username')
        user_id = user.get('telegram_id')
        user_list_text += f"- {name} (@{username or 'N/A'}) [ID: `{user_id}`]\n"

    await update.message.reply_text(user_list_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to send a message to all users."""
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
        return

    message_text = " ".join(context.args)
    all_user_ids = await get_all_user_telegram_ids()

    if not all_user_ids:
        await update.message.reply_text("No users to broadcast to.")
        return

    await update.message.reply_text(f"Broadcasting message to {len(all_user_ids)} users...")

    sent_count = 0
    blocked_count = 0

    async def send_message_to_user(user_id):
        nonlocal sent_count, blocked_count
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Could not send broadcast message to user {user_id}: {e}")
            blocked_count += 1

    # Send messages concurrently
    await asyncio.gather(*(send_message_to_user(user_id) for user_id in all_user_ids))

    await update.message.reply_text(
        f"Broadcast complete.\nSent to: {sent_count}\nFailed (blocked/etc): {blocked_count}"
    )

@admin_only
async def confirm_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to confirm a user's payment."""
    if not context.args:
        await update.message.reply_text("Usage: `/confirm_payment <user_telegram_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        user_to_confirm_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID format.")
        return

    if user_to_confirm_id not in pending_payments:
        await update.message.reply_text(f"No pending payment found for user ID `{user_to_confirm_id}`.")
        return

    payment_info = pending_payments.pop(user_to_confirm_id)
    claimed_amount = payment_info['amount']
    payment_date = payment_info['date']
    original_message_id = payment_info['message_id']

    # --- Process Confirmation ---
    # 1. Increment tickets for the user for the payment date
    await increment_daily_tickets(user_to_confirm_id)

    # 2. Handle Referral Bonus
    referred_user = await get_user(user_to_confirm_id)
    if referred_user and referred_user.get('referrer_telegram_id'):
        referrer_id = referred_user['referrer_telegram_id']
        referral_bonus = claimed_amount * REFERRAL_PERCENT
        if referral_bonus > 0:
            # Simulate sending referral bonus to referrer (Need referrer's USDT address - not stored)
            # For this simulation, we just log and notify. A real bot needs address collection.
            referrer_info_str = f"Referrer ID: {referrer_id} (Address needed)"
            await simulate_send_usdt(referrer_info_str, referral_bonus, "Referral Bonus")

            # Notify referrer
            try:
                referred_user_name = referred_user.get('first_name', f'User {user_to_confirm_id}')
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"Referral Bonus Received! \n\n" # Removed 💰 💰
                         f"You earned *{referral_bonus:.2f} USDT* because your referral {referred_user_name} bought a ticket!\n"
                         "Keep sharing your link to earn more!",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified referrer {referrer_id} of bonus from {user_to_confirm_id}")
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_id} about bonus: {e}")


    # 3. Notify the user whose payment was confirmed
    try:
        tickets_today = await get_todays_total_tickets() # This gets global total, not user specific. Re-query user's count.
        user_todays_tickets_res = supabase.from_('daily_tickets').select('count').eq('telegram_id', user_to_confirm_id).eq('date', datetime.date.today().isoformat()).single().execute()
        user_todays_count = user_todays_tickets_res.data['count'] if user_todays_tickets_res.data else 0


        await context.bot.send_message(
            chat_id=user_to_confirm_id,
            text=f"Your payment of {claimed_amount:.2f} USDT has been confirmed!\n" # Removed ✅
                 f"You now have *{user_todays_count}* ticket(s) for today's draw! Good luck! ", # Removed 🍀
            parse_mode=ParseMode.MARKDOWN
        )
        # Try to edit the original "pending" message if possible
        try:
             await context.bot.edit_message_text(
                 chat_id=user_to_confirm_id,
                 message_id=original_message_id,
                 text=f"Your payment of {claimed_amount:.2f} USDT has been confirmed!\n" # Removed ✅
                 f"You now have *{user_todays_count}* ticket(s) for today's draw! Good luck! ", # Removed 🍀
                 parse_mode=ParseMode.MARKDOWN
             )
        except Exception as edit_e:
             logger.warning(f"Failed to edit original payment message for {user_to_confirm_id}: {edit_e}")

        logger.info(f"Payment confirmed for user {user_to_confirm_id}. Tickets added.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_to_confirm_id} about payment confirmation: {e}")


    await update.message.reply_text(f"Payment confirmed for user ID `{user_to_confirm_id}`. Tickets added and referral bonus processed (if applicable).")


@admin_only
async def manual_winner_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to manually trigger winner draw for the previous day."""
    await update.message.reply_text("Triggering manual winner draw for the previous day...")
    # Draw winner for yesterday's tickets
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    await draw_winner(context, date_override=yesterday)
    await update.message.reply_text("Manual winner draw process complete.")


# --- Scheduled Jobs ---

async def draw_winner(context: ContextTypes.DEFAULT_TYPE, date_override: datetime.date | None = None) -> None:
    """Scheduled job to draw a winner."""
    # Determine the date for the draw (usually yesterday's tickets)
    draw_date = date_override if date_override else datetime.date.today() - datetime.timedelta(days=1)
    logger.info(f"Starting winner draw for tickets purchased on {draw_date.isoformat()}")

    ticket_entries = await get_daily_ticket_counts(draw_date)

    if not ticket_entries:
        logger.info(f"No tickets bought on {draw_date.isoformat()}. No winner.")
        broadcast_text = (
            f"Daily Draw Results for {draw_date.isoformat()} \n\n" # Removed 🏆 🏆
            "Looks like no one bought tickets yesterday. \n" # Removed 😔
            "No winner for this draw. Buy tickets today for a chance to win tomorrow!"
        )
        # Broadcast "No winner" message
        user_ids = await get_all_user_telegram_ids()
        await broadcast_message_to_users(context, user_ids, broadcast_text)
        return

    # Create a list where each user_id appears 'count' times
    ticket_list = []
    for entry in ticket_entries:
        ticket_list.extend([entry['telegram_id']] * entry['count'])

    winner_telegram_id = random.choice(ticket_list)

    # Get winner details
    winner_user = await get_user(winner_telegram_id)
    winner_name = winner_user.get('first_name', f'User {winner_telegram_id}') if winner_user else f'User {winner_telegram_id}'
    winner_username = winner_user.get('username', 'N/A') if winner_user else 'N/A'

    # Simulate sending prize (Needs winner's USDT address - not stored)
    # For simulation, just log and notify. Real bot needs address collection.
    winner_info_str = f"Winner ID: {winner_telegram_id} (Address needed)"
    await simulate_send_usdt(winner_info_str, WINNER_AMOUNT_USDT, "Winner Prize")

    # Record winner in DB
    await add_winner(winner_telegram_id, WINNER_AMOUNT_USDT, draw_date)

    # Broadcast winner announcement
    broadcast_text = (
        f"Daily Draw Results for {draw_date.isoformat()} \n\n" # Removed 🏆 🏆
        f"And the winner is... *{winner_name}* (@{winner_username})!\n"
        f"Congratulations! You have won *{WINNER_AMOUNT_USDT:.2f} USDT*!\n\n"
        "Buy your tickets today using /buy for a chance to be the next winner! " # Removed 🚀
    )

    user_ids = await get_all_user_telegram_ids()
    await broadcast_message_to_users(context, user_ids, broadcast_text, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Winner {winner_telegram_id} drawn and announced for {draw_date.isoformat()}")


async def send_daily_marketing_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job to send a daily marketing message."""
    message_content = await get_random_marketing_message()

    if not message_content:
        logger.warning("No marketing messages found in DB to send.")
        return

    logger.info("Sending daily marketing message...")
    user_ids = await get_all_user_telegram_ids()
    if not user_ids:
        logger.info("No users to send marketing message to.")
        return

    await broadcast_message_to_users(context, user_ids, message_content)
    logger.info("Daily marketing message sent.")


async def broadcast_message_to_users(context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str, parse_mode: ParseMode | None = None):
     """Helper to send a message to a list of user IDs concurrently."""
     async def send_single_message(user_id):
         try:
             await context.bot.send_message(chat_id=user_id, text=text, parse_mode=parse_mode)
             return True
         except Exception as e:
             # Log specific errors like Blocked by the user
             logger.warning(f"Failed to send message to user {user_id}: {e}")
             return False

     tasks = [send_single_message(user_id) for user_id in user_ids]
     results = await asyncio.gather(*tasks)
     sent_count = sum(results)
     failed_count = len(user_ids) - sent_count
     logger.info(f"Broadcasted message. Sent: {sent_count}, Failed: {failed_count}")


# --- Winners History ---

async def winners_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the last 7 winners (real + fake)."""
    latest_real_winners = await get_latest_winners(7)
    num_real_winners = len(latest_real_winners)

    winners_list_text = "TrustWin Bot Latest Winners \n\n" # Removed 🏆 🏆

    if num_real_winners == 0:
        winners_list_text += "No winners yet! Be the first!\n\n"

    # Generate fake winners to fill up to 7, sorting them by date (mixed with real)
    all_winners_display = latest_real_winners[:] # Copy real winners
    num_fake_needed = 7 - num_real_winners

    fake_names = ["Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy"]
    fake_amounts = [Decimal("2.50"), Decimal("5.00"), Decimal("10.00"), Decimal("7.50")] # Variety of fake amounts

    # Generate fake entries for dates before the earliest real winner or for past 7 days if no real winners
    last_real_date = latest_real_winners[-1]['win_date'] if latest_real_winners else datetime.date.today() - datetime.timedelta(days=7)
    for i in range(num_fake_needed):
        fake_date = last_real_date - datetime.timedelta(days=i+1)
        fake_winner_data = {
            'win_date': fake_date,
            'amount': random.choice(fake_amounts),
            'user_info': {'first_name': random.choice(fake_names), 'username': None} # Fake name, no username
        }
        all_winners_display.append(fake_winner_data)

    # Sort all entries (real + fake) by date descending
    all_winners_display.sort(key=lambda x: x['win_date'], reverse=True)

    # Format the list
    for winner_entry in all_winners_display:
        win_date = winner_entry['win_date']
        amount = winner_entry['amount']
        user_info = winner_entry['user_info']

        name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
        # We don't show fake usernames to distinguish slightly
        # username = user_info.get('username') if user_info else None
        # user_display = f"{name} (@{username})" if username else name

        # Make fake entries look slightly different or just present the name
        is_real = 'telegram_id' in winner_entry # Check if it has a telegram_id key (only real ones will)

        name_display = f"*{name}*"
        if not is_real:
             name_display = f"_{name}_ (Fake)" # Indicate fake entry

        winners_list_text += f"Date: {win_date.isoformat()}: {name_display} won *{amount:.2f} USDT*\n" # Removed 📅

    await update.message.reply_text(winners_list_text, parse_mode=ParseMode.MARKDOWN)


# --- Error Handling ---

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error}")

    # Send error message to admin
    try:
        # traceback.format_exc() might be too long, summarize
        error_message = f"An error occurred: {context.error}\nUpdate: {update}"
        if len(error_message) > 4000: # Telegram message limit
             error_message = error_message[:3900] + "...\n(Message truncated)"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"Bot Error Alert \n\n{error_message}" # Removed ⚠️ ⚠️
        )
    except Exception as e:
        logger.error(f"Failed to send error notification to admin {ADMIN_ID}: {e}")


# --- Main Function ---

def main() -> None:
    """Start the bot."""
    logger.info("Starting TrustWin Bot...")

    # Build the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Get the job queue
    job_queue = application.job_queue

    # Set timezone for scheduler
    timezone = pytz.timezone(TIMEZONE_STR)

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("winners", winners_command))

    # Admin command handlers (using the decorator)
    application.add_handler(CommandHandler("stats", admin_only(stats_command)))
    application.add_handler(CommandHandler("users", admin_only(users_command)))
    application.add_handler(CommandHandler("broadcast", admin_only(broadcast_command)))
    application.add_handler(CommandHandler("confirm_payment", admin_only(confirm_payment_command)))
    application.add_handler(CommandHandler("winner", admin_only(manual_winner_draw_command))) # Manual trigger

    # Add callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(paid_button_callback, pattern='^paid_'))

    # Add error handler
    application.add_error_handler(error_handler)

    # Schedule jobs
    # Winner draw daily at 12:01 AM IST
    job_queue.run_daily(
        draw_winner,
        time=datetime.time(hour=0, minute=1, second=0, tzinfo=timezone),
        days=(0, 1, 2, 3, 4, 5, 6), # Run every day of the week
        name="daily_winner_draw"
    )
    logger.info(f"Scheduled daily winner draw at 12:01 AM {TIMEZONE_STR}")

    # Daily marketing message at 9:00 AM IST
    job_queue.run_daily(
        send_daily_marketing_message,
        time=datetime.time(hour=9, minute=0, second=0, tzinfo=timezone),
        days=(0, 1, 2, 3, 4, 5, 6), # Run every day of the week
        name="daily_marketing_message"
    )
    logger.info(f"Scheduled daily marketing message at 9:00 AM {TIMEZONE_STR}")

    # Start the Bot
    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
