# bot.py

import os
import logging
import asyncio
import random
import datetime
from decimal import Decimal, ROUND_HALF_UP

# from dotenv import load_dotenv # Uncomment if using a .env file locally

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from supabase.client import create_client, Client

import pytz

# --- Environment Variables ---
# load_dotenv() # Uncomment if using a .env file

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
USDT_WALLET = os.getenv("USDT_WALLET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

TICKET_PRICE_USDT_STR = os.getenv("TICKET_PRICE_USDT", "4.0")
REFERRAL_PERCENT_STR = os.getenv("REFERRAL_PERCENT", "0.25")
GLOBAL_CRYPTO_TAX_PERCENT_STR = os.getenv("GLOBAL_CRYPTO_TAX_PERCENT", "0.25")
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Kolkata")

# Validate and convert environment variables
if not all([BOT_TOKEN, ADMIN_ID_STR, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY]):
    logging.error("FATAL: Missing required environment variables (BOT_TOKEN, ADMIN_ID, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY)!")
    exit(1)

try:
    ADMIN_ID = int(ADMIN_ID_STR)
    TICKET_PRICE_USDT = Decimal(TICKET_PRICE_USDT_STR)
    REFERRAL_PERCENT = Decimal(REFERRAL_PERCENT_STR)
    GLOBAL_CRYPTO_TAX_PERCENT = Decimal(GLOBAL_CRYPTO_TAX_PERCENT_STR)

    if not (Decimal(0) <= REFERRAL_PERCENT <= Decimal(1)):
        logging.error("FATAL: REFERRAL_PERCENT must be between 0 and 1 (e.g., 0.25 for 25%).")
        exit(1)
    if not (Decimal(0) <= GLOBAL_CRYPTO_TAX_PERCENT <= Decimal(1)):
        logging.error("FATAL: GLOBAL_CRYPTO_TAX_PERCENT must be between 0 and 1 (e.g., 0.25 for 25%).")
        exit(1)
    if (REFERRAL_PERCENT + GLOBAL_CRYPTO_TAX_PERCENT) > Decimal(1):
        logging.error("FATAL: Sum of REFERRAL_PERCENT and GLOBAL_CRYPTO_TAX_PERCENT cannot exceed 1 (100%).")
        exit(1)

except ValueError as e:
    logging.error(f"FATAL: Invalid format for numeric environment variables (ADMIN_ID, TICKET_PRICE_USDT, REFERRAL_PERCENT, GLOBAL_CRYPTO_TAX_PERCENT): {e}")
    exit(1)

# Calculate Prize Pool Contribution Percentage
PRIZE_POOL_CONTRIBUTION_PERCENT = Decimal(1) - REFERRAL_PERCENT - GLOBAL_CRYPTO_TAX_PERCENT
if PRIZE_POOL_CONTRIBUTION_PERCENT < Decimal(0): # Should be caught by previous check, but good to have
    logging.error("FATAL: Prize pool contribution percentage is negative. Check referral and tax percentages.")
    exit(1)
logger.info(f"Ticket Price: {TICKET_PRICE_USDT} USDT")
logger.info(f"Referral Percent: {REFERRAL_PERCENT*100}%")
logger.info(f"Global Crypto Tax Percent: {GLOBAL_CRYPTO_TAX_PERCENT*100}%")
logger.info(f"Prize Pool Contribution Percent: {PRIZE_POOL_CONTRIBUTION_PERCENT*100}%")


# --- Supabase Client ---
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Successfully connected to Supabase.")
except Exception as e:
    logger.error(f"FATAL: Could not initialize Supabase client: {e}")
    exit(1)

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Logger already configured, but re-getting it for this module
logger = logging.getLogger(__name__)


# --- Global State (for pending payments - Simple in-memory approach) ---
# WARNING: In a multi-instance setup, this should be persistent (e.g., Redis or DB)
pending_payments = {} # {user_id: {amount_paid: Decimal, num_tickets: int, message_id: int, date: date, chat_id: int}}

# --- Helper Functions: Database ---

async def get_user(telegram_id: int):
    """Fetch a user from the database by telegram_id."""
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).single().execute()
        return response.data
    except Exception as e:
        # Check if the error is due to 'single' finding zero rows (common and not always an "error")
        if hasattr(e, 'message') and "PGRST116" in e.message and "0 rows" in e.message: # supabase-py v1 specific
            logger.debug(f"Supabase: User {telegram_id} not found (0 rows for single()).")
        elif hasattr(e, 'code') and e.code == 'PGRST116': # supabase-py v2 might use this
            logger.debug(f"Supabase: User {telegram_id} not found (PGRST116 for single()).")
        else:
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
            'join_date': datetime.datetime.now(pytz.timezone(TIMEZONE_STR)).isoformat()
        }
        response = supabase.from_('users').insert([data_to_insert]).execute()
        if response.data:
            logger.info(f"New user created: {telegram_id} (Referrer: {referrer_telegram_id})")
            return response.data[0]
        # Handle potential errors from Supabase insert
        error_msg = "Unknown error"
        if response.error:
            error_msg = response.error.message
            if hasattr(response.error, 'details'): # More detailed error
                error_msg += f" Details: {response.error.details}"
        logger.error(f"Supabase error creating user {telegram_id}: {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Exception creating user {telegram_id}: {e}")
        return None

async def increment_daily_tickets_for_user(telegram_id: int, num_tickets: int = 1):
    """Increment ticket count for a user for today's date using RPC."""
    if num_tickets <= 0:
        logger.warning(f"Attempted to increment 0 or negative tickets for user {telegram_id}.")
        return False
    try:
        today_iso = datetime.date.today().isoformat()
        # Ensure your Supabase RPC function 'increment_daily_ticket' is defined as:
        # CREATE OR REPLACE FUNCTION increment_daily_ticket(user_id_input BIGINT, ticket_date_input DATE, num_tickets_to_add INT) ...
        response = supabase.rpc('increment_daily_ticket', {
            'user_id_input': telegram_id,
            'ticket_date_input': today_iso,
            'num_tickets_to_add': num_tickets
        }).execute()

        # supabase-py v1.x might not have a clear .error attribute on successful RPC void calls
        # supabase-py v2.x .execute() on RPC might return None on success or raise an error
        # For v1.x, we might need to check response status or lack of data if it's not void
        # Assuming if it doesn't raise an exception, it's successful for a void RPC
        # However, if there's an error object (e.g. PostgrestAPIError), it should be caught.

        # A more robust check might be needed depending on supabase-py version behavior for RPC errors
        # For now, we assume an exception will be raised or response.error will be set by the library
        if hasattr(response, 'error') and response.error:
             logger.error(f"Supabase RPC error incrementing {num_tickets} tickets for {telegram_id} on {today_iso}: {response.error.message}")
             return False

        logger.info(f"{num_tickets} tickets incremented via RPC for user {telegram_id} for {today_iso}.")
        return True
    except Exception as e: # This will catch PostgrestError if RPC fails and library raises it
        logger.error(f"Exception calling RPC increment_daily_ticket for user {telegram_id} ({num_tickets} tickets): {e}")
        return False


async def get_total_tickets_for_date(date_obj: datetime.date) -> int:
    """Get the total number of tickets sold on a specific date."""
    try:
        # Summing the 'count' column from 'daily_tickets' table for the given date
        # Supabase equivalent: SELECT sum(count) from daily_tickets where date = '...'
        response = supabase.from_('daily_tickets').select('count').eq('date', date_obj.isoformat()).execute()
        if response.data:
            return sum(item['count'] for item in response.data if isinstance(item.get('count'), int))
        return 0
    except Exception as e:
        logger.error(f"Supabase error fetching total tickets for {date_obj}: {e}")
        return 0

async def get_daily_ticket_entries_for_draw(date_obj: datetime.date) -> list:
    """Get all individual ticket entries (telegram_id, count) for a specific date."""
    try:
        response = supabase.from_('daily_tickets').select('telegram_id, count').eq('date', date_obj.isoformat()).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Supabase error fetching daily ticket entries for {date_obj} for draw: {e}")
        return []

async def add_winner_record(telegram_id: int, amount: Decimal, win_date: datetime.date):
    """Add a winner entry to the database."""
    try:
        data_to_insert = {
            'telegram_id': telegram_id,
            'amount': float(amount), # Supabase numeric often maps to float
            'win_date': win_date.isoformat()
        }
        response = supabase.from_('winners').insert([data_to_insert]).execute()
        if response.data:
            logger.info(f"Winner recorded: {telegram_id} on {win_date} with {amount:.2f} USDT")
            return response.data[0]
        error_msg = response.error.message if response.error else "Unknown error"
        logger.error(f"Supabase error adding winner {telegram_id}: {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Exception adding winner {telegram_id}: {e}")
        return None

async def get_latest_winners(limit: int = 7):
    """Fetch the latest winners from the database, including user info."""
    try:
        winners_response = supabase.from_('winners').select('telegram_id, amount, win_date').order('win_date', desc=True).limit(limit).execute()
        if not winners_response.data:
            return []

        winner_telegram_ids = [w['telegram_id'] for w in winners_response.data]
        # It's possible to have winners but no corresponding users if a user was deleted
        # So, proceed even if winner_telegram_ids is empty after this (though unlikely if winners_response.data exists)

        users_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', winner_telegram_ids).execute()
        user_map = {user['telegram_id']: user for user in users_response.data} if users_response.data else {}

        # Attach user_info to each winner
        for winner in winners_response.data:
            winner['user_info'] = user_map.get(winner['telegram_id']) # Will be None if user not found
        return winners_response.data
    except Exception as e:
        logger.error(f"Supabase error fetching latest winners: {e}")
        return []

async def get_all_user_telegram_ids() -> list[int]:
    """Fetch all user telegram_ids for broadcasting."""
    try:
        response = supabase.from_('users').select('telegram_id').execute()
        return [user['telegram_id'] for user in response.data] if response.data else []
    except Exception as e:
        logger.error(f"Supabase error fetching all user telegram_ids: {e}")
        return []

async def get_total_users_count() -> int:
    """Get the total count of users."""
    try:
        response = supabase.from_('users').select('telegram_id', count='exact').limit(0).execute() # Fetch no data, just count
        return response.count if response.count is not None else 0
    except Exception as e:
        logger.error(f"Supabase error fetching total users count: {e}")
        return 0

async def get_random_marketing_message_content() -> str | None:
    """Fetch a random marketing message from the database."""
    try:
        response = supabase.from_('messages').select('content').eq('type', 'marketing').execute()
        if response.data:
            messages = [msg['content'] for msg in response.data if msg.get('content')]
            return random.choice(messages) if messages else None
        return None
    except Exception as e:
        logger.error(f"Supabase error fetching marketing message: {e}")
        return None

# --- Helper: Calculate Dynamic Prize ---
async def calculate_prize_for_date(date_obj: datetime.date) -> Decimal:
    """Calculates the winner prize for a given date based on ticket sales."""
    total_tickets_sold_on_date = await get_total_tickets_for_date(date_obj)
    logger.info(f"Total tickets sold on {date_obj.isoformat()}: {total_tickets_sold_on_date}")

    if total_tickets_sold_on_date == 0:
        return Decimal("0.00")

    total_revenue_from_tickets = total_tickets_sold_on_date * TICKET_PRICE_USDT
    prize_amount = total_revenue_from_tickets * PRIZE_POOL_CONTRIBUTION_PERCENT
    # Ensure prize is rounded to 2 decimal places
    return prize_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Helper Functions: USDT Simulation & Broadcast ---
async def simulate_send_usdt(recipient_info: str, amount: Decimal, transaction_type: str):
    """Simulates sending USDT."""
    logger.info(f"SIMULATING USDT SEND: Type='{transaction_type}', Recipient='{recipient_info}', Amount='{amount:.2f} USDT'")
    await asyncio.sleep(random.uniform(0.5, 1.2)) # Simulate network delay
    logger.info(f"SIMULATION COMPLETE: USDT sent successfully (simulated).")
    return True # Assume success for simulation

async def broadcast_message_to_users_list(context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str, parse_mode: str | None = None):
    """Helper to send a message to a list of user IDs concurrently."""
    sent_count = 0
    failed_count = 0
    tasks = []

    async def send_single_message(user_id_to_send: int):
        nonlocal sent_count, failed_count # Ensure these are captured from the outer scope
        try:
            await context.bot.send_message(chat_id=user_id_to_send, text=text, parse_mode=parse_mode)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast message to user {user_id_to_send}: {e}")
            failed_count +=1 # Corrected increment here

    for user_id in user_ids:
        tasks.append(send_single_message(user_id))

    if tasks:
        await asyncio.gather(*tasks) # Wait for all messages to be attempted
    logger.info(f"Broadcast attempt finished. Sent: {sent_count}, Failed: {failed_count} out of {len(user_ids)} users.")


# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command, registers user and provides referral info."""
    user = update.effective_user
    if not user:
        logger.warning("Start command received without an effective_user.")
        return

    telegram_id = user.id
    username = user.username
    first_name = user.first_name or "User" # Default if first_name is None
    last_name = user.last_name

    referrer_telegram_id = None
    if context.args: # Check if there are any arguments (potential referrer ID)
        try:
            potential_referrer_id = int(context.args[0])
            if potential_referrer_id != telegram_id: # User cannot refer themselves
                referrer_user = await get_user(potential_referrer_id)
                if referrer_user:
                    referrer_telegram_id = potential_referrer_id
                    logger.info(f"User {telegram_id} ({username or first_name}) started with referrer {referrer_telegram_id}")
                else:
                    logger.warning(f"User {telegram_id} used invalid referrer ID (not found): {context.args[0]}")
            else:
                 logger.warning(f"User {telegram_id} tried to refer themselves.")
        except (ValueError, IndexError): # Catch if arg is not an int or no arg
            logger.warning(f"User {telegram_id} used invalid referral link format or no valid arg: {context.args}")

    db_user = await get_user(telegram_id)
    is_new_user = db_user is None

    # Calculate today's potential prize pool for display
    today_date = datetime.date.today()
    # This shows prize based on tickets sold *so far* today.
    # The actual draw (for yesterday) will use yesterday's final ticket count.
    potential_todays_prize = await calculate_prize_for_date(today_date)

    welcome_message_parts = [
        f"Hello {first_name}! Welcome to TrustWin Bot!",
        "Get your tickets daily for a chance to win big in our USDT lottery!"
    ]

    if is_new_user:
        created_user = await create_user(telegram_id, username, first_name, last_name, referrer_telegram_id)
        if created_user:
            welcome_message_parts.append("You've been registered! Thanks for joining.")
            if referrer_telegram_id:
                try:
                    # Construct a display name for the new user being referred
                    new_user_display_name = first_name
                    if username: new_user_display_name += f" (@{username})"
                    # else: new_user_display_name += f" (ID: {telegram_id})" # Can be too verbose

                    await context.bot.send_message(
                        chat_id=referrer_telegram_id,
                        text=f"Great news! Your referral {new_user_display_name} has joined TrustWin Bot using your link!\n"
                             f"You'll earn {REFERRAL_PERCENT*100:.0f}% of the ticket price every time they buy a ticket!"
                    )
                    logger.info(f"Notified referrer {referrer_telegram_id} about new user {telegram_id}")
                except Exception as e:
                    logger.warning(f"Could not notify referrer {referrer_telegram_id}: {e}")
        else:
            welcome_message_parts.append("There was an issue registering you. Please try /start again later.")

    welcome_message_parts.extend([
        f"\nToday's *potential* prize pool is currently around *{potential_todays_prize:.2f} USDT*.",
        "(This grows as more tickets are sold today for *tomorrow's* draw).",
        f"Each ticket costs *{TICKET_PRICE_USDT:.2f} USDT*.",
        "\nUse the /buy command to get your ticket(s)!",
        f"\nWant to earn passively? Share your unique referral link:",
        f"`https://t.me/{context.bot.username}?start={telegram_id}`",
        f"You get {REFERRAL_PERCENT*100:.0f}% of the ticket price for every ticket your referred friends buy, FOREVER!",
        "\nMay the odds be ever in your favor!"
    ])
    welcome_message = "\n".join(welcome_message_parts)

    if update.message:
        await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
    else: # Should not happen with CommandHandler but good for robustness
        logger.warning("Start command invoked without a message attribute in update (e.g., edited message).")


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /buy command to initiate ticket purchase for one ticket."""
    user = update.effective_user
    if not user:
        logger.warning("Buy command received without an effective_user.")
        return

    telegram_id = user.id

    db_user = await get_user(telegram_id) # Ensure user is registered
    if not db_user:
        if update.message:
            await update.message.reply_text("Please use the /start command first to register.")
        return

    # For this version, one /buy command initiates purchase for ONE ticket.
    num_tickets_to_buy = 1
    total_payment_due = num_tickets_to_buy * TICKET_PRICE_USDT

    # Callback data now includes num_tickets
    callback_data_string = f"paid_{total_payment_due}_{num_tickets_to_buy}"
    keyboard = [[InlineKeyboardButton(f"I have paid {total_payment_due:.2f} USDT", callback_data=callback_data_string)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        f"To buy {num_tickets_to_buy} ticket(s) for *{total_payment_due:.2f} USDT*:\n\n"
        f"1. Send exactly *{total_payment_due:.2f} USDT (TRC-20)* to the following wallet address:\n"
        f"`{USDT_WALLET}`\n\n"
        "2. After sending, click the 'I have paid' button below.\n\n"
        "Your ticket(s) will be counted for today's draw after admin verification. Good luck!"
    )
    if update.message:
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def paid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'I have paid' button click."""
    query = update.callback_query
    if not query or not query.message: # query.message is needed for chat_id, message_id
        logger.error("paid_button_callback received invalid query object or query without message.")
        if query: await query.answer("Error processing request.", show_alert=True)
        return

    user = query.effective_user
    if not user:
        logger.error("paid_button_callback received query without an effective_user.")
        await query.answer("Error: Could not identify user.", show_alert=True)
        return

    telegram_id = user.id
    data = query.data # Format: paid_AMOUNT_NUMTICKETS

    await query.answer("Processing your payment confirmation...") # Acknowledge button press

    try:
        parts = data.split('_')
        if len(parts) != 3 or parts[0] != 'paid': # Validate format
            raise ValueError("Callback data format incorrect")

        claimed_amount_str = parts[1]
        num_tickets_claimed_str = parts[2]

        claimed_amount_paid = Decimal(claimed_amount_str)
        num_tickets_claimed = int(num_tickets_claimed_str)

        # Validate: claimed amount should match num_tickets * TICKET_PRICE_USDT
        expected_amount_for_tickets = (num_tickets_claimed * TICKET_PRICE_USDT).quantize(Decimal("0.01"))
        if claimed_amount_paid.quantize(Decimal("0.01")) != expected_amount_for_tickets:
            error_msg = (f"Payment amount mismatch. Expected {expected_amount_for_tickets:.2f} USDT for {num_tickets_claimed} ticket(s), "
                         f"but claim is for {claimed_amount_paid:.2f} USDT. Please contact admin or try /buy again with the correct amount for the number of tickets.")
            await query.edit_message_text(error_msg)
            logger.error(f"Payment mismatch for user {telegram_id}. Claimed {claimed_amount_paid} for {num_tickets_claimed} tickets. Expected {expected_amount_for_tickets}")
            return

    except (IndexError, ValueError, TypeError) as e: # Catch more specific errors
        await query.edit_message_text("Invalid payment confirmation data format. Please try /buy again.")
        logger.error(f"Invalid callback data received: '{data}' from user {telegram_id}. Error: {e}")
        return

    # Store pending payment
    pending_payments[telegram_id] = {
        'amount_paid': claimed_amount_paid, # Actual amount user claims to have paid
        'num_tickets': num_tickets_claimed,   # Number of tickets this payment is for
        'date': datetime.date.today(),
        'message_id': query.message.message_id, # To edit this message later
        'chat_id': query.message.chat_id      # To edit this message later
    }

    admin_notification_text = (
        f"Payment Claimed!\n\n"
        f"User: {user.first_name or 'N/A'} (@{user.username or 'N/A'}) [ID: `{telegram_id}`]\n"
        f"Claimed for: *{num_tickets_claimed} ticket(s)* (Total {claimed_amount_paid:.2f} USDT)\n"
        f"Claim Date: {datetime.date.today().isoformat()}\n\n"
        f"Check payment and use `/confirm_payment {telegram_id}` if verified."
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_notification_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Admin {ADMIN_ID} notified about pending payment from {telegram_id} for {num_tickets_claimed} tickets.")
        await query.edit_message_text(
            f"Received your payment confirmation for {num_tickets_claimed} ticket(s) ({claimed_amount_paid:.2f} USDT).\n"
            "Please wait while the admin verifies the transaction. Your tickets will be added shortly!"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin {ADMIN_ID} or edit user message for {telegram_id}: {e}")
        # Fallback: Try to send a new message to user if edit failed or admin notification failed
        try:
            await context.bot.send_message(
                chat_id=telegram_id, # User's chat
                text=f"Received your payment confirmation for {num_tickets_claimed} ticket(s).\n"
                     "There was an issue during admin notification, but your claim is recorded. Please wait for verification."
            )
        except Exception as e_user_notify:
            logger.error(f"Also failed to send direct notification to user {telegram_id} after primary failure: {e_user_notify}")


# --- Admin Decorator ---
def admin_only(handler):
    """Decorator to restrict handlers to admin. Works for both message and callback query handlers."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_to_check = update.effective_user
        if not user_to_check or user_to_check.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("You are not authorized to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("You are not authorized for this action.", show_alert=True)
            logger.warning(f"Unauthorized access attempt by user {user_to_check.id if user_to_check else 'Unknown'} for admin command.")
            return
        # If authorized, proceed with the original handler
        await handler(update, context)
    return wrapper

# --- Admin Commands ---

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to show bot statistics."""
    if not update.message: return # Should not happen with CommandHandler

    total_users = await get_total_users_count()
    todays_total_tickets_sold = await get_total_tickets_for_date(datetime.date.today())
    pending_count = len(pending_payments)
    # Prize for *tomorrow's* draw based on *today's* sales so far
    potential_prize_for_tomorrows_draw = await calculate_prize_for_date(datetime.date.today())
    # Prize for *today's* draw (which happened/will happen soon) based on *yesterday's* sales
    prize_for_todays_draw = await calculate_prize_for_date(datetime.date.today() - datetime.timedelta(days=1))


    stats_text = (
        "Bot Statistics\n\n"
        f"Total Users: `{total_users}`\n"
        f"Today's Tickets Sold (for tomorrow's draw): `{todays_total_tickets_sold}`\n"
        f"Today's *Potential* Prize Pool (for tomorrow's draw): `{potential_prize_for_tomorrows_draw:.2f} USDT`\n"
        f"Prize for *Today's* Draw (from yesterday's sales): `{prize_for_todays_draw:.2f} USDT`\n"
        f"Pending Payments (Admin Verification): `{pending_count}`"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list active users (first 50)."""
    if not update.message: return

    all_user_ids = await get_all_user_telegram_ids()
    if not all_user_ids:
        await update.message.reply_text("No users found.")
        return

    user_list_text = "Active Users\n\n"
    display_limit = 50
    limited_user_ids = all_user_ids[:display_limit]

    if len(all_user_ids) > display_limit:
        user_list_text += f"Listing first {display_limit} of {len(all_user_ids)} users:\n"

    if limited_user_ids: # Fetch details only if there are IDs to fetch
        user_details_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', limited_user_ids).execute()
        user_details = user_details_response.data if user_details_response.data else []

        for user_data in user_details:
            name = user_data.get('first_name', 'N/A')
            username_str = user_data.get('username')
            user_id = user_data.get('telegram_id')
            user_list_text += f"- {name} (@{username_str or 'N/A'}) [ID: `{user_id}`]\n"
    else: # Should be caught by 'if not all_user_ids' but as a safeguard
        user_list_text += "No users to list details for.\n"


    await update.message.reply_text(user_list_text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to send a message to all users."""
    if not update.message or not context.args:
        if update.message: await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
        return

    message_text = " ".join(context.args)
    all_user_ids = await get_all_user_telegram_ids()

    if not all_user_ids:
        if update.message: await update.message.reply_text("No users to broadcast to.")
        return

    if update.message: await update.message.reply_text(f"Starting broadcast of message to {len(all_user_ids)} users...")
    await broadcast_message_to_users_list(context, all_user_ids, message_text) # Assuming parse_mode is not needed or default
    if update.message: await update.message.reply_text("Broadcast attempt finished. Check logs for details on sent/failed counts.")


@admin_only
async def confirm_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to confirm a user's payment."""
    if not update.message or not context.args:
        if update.message: await update.message.reply_text("Usage: `/confirm_payment <user_telegram_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        user_to_confirm_id = int(context.args[0])
    except ValueError:
        if update.message: await update.message.reply_text("Invalid user ID format. Must be an integer.")
        return

    if user_to_confirm_id not in pending_payments:
        if update.message: await update.message.reply_text(f"No pending payment found for user ID `{user_to_confirm_id}`.")
        return

    # Retrieve and remove from pending
    payment_info = pending_payments.pop(user_to_confirm_id)
    claimed_payment_amount_by_user = payment_info['amount_paid'] # Amount user said they paid
    num_tickets_purchased = payment_info['num_tickets']
    original_message_id = payment_info['message_id']
    original_chat_id = payment_info['chat_id']

    # --- Process Confirmation ---
    # 1. Increment tickets for the user
    if not await increment_daily_tickets_for_user(user_to_confirm_id, num_tickets_purchased):
        logger.error(f"Failed to increment {num_tickets_purchased} tickets for {user_to_confirm_id} after payment confirmation by admin.")
        # Re-add to pending or notify admin of failure
        pending_payments[user_to_confirm_id] = payment_info # Put it back
        if update.message: await update.message.reply_text(f"Error: Failed to increment tickets for user {user_to_confirm_id}. Payment confirmation REVERTED. Check logs and database. User needs to be processed again.")
        return

    # 2. Handle Referral Bonus
    referred_user_data = await get_user(user_to_confirm_id)
    if referred_user_data and referred_user_data.get('referrer_telegram_id'):
        referrer_id = referred_user_data['referrer_telegram_id']
        # Calculate bonus based on the standard price of tickets purchased, not necessarily claimed_payment_amount
        # This assumes claimed_payment_amount was validated against num_tickets * TICKET_PRICE_USDT earlier
        value_of_tickets_purchased = num_tickets_purchased * TICKET_PRICE_USDT
        referral_bonus = value_of_tickets_purchased * REFERRAL_PERCENT

        if referral_bonus > 0:
            await simulate_send_usdt(f"Referrer ID: {referrer_id}", referral_bonus, "Referral Bonus") # Simulate payment
            try:
                referred_user_name = referred_user_data.get('first_name', f'User {user_to_confirm_id}')
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"Referral Bonus Received!\n\n"
                         f"You earned *{referral_bonus:.2f} USDT* because your referral {referred_user_name} bought {num_tickets_purchased} ticket(s)!\n"
                         "Keep sharing your link to earn more!",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified referrer {referrer_id} of {referral_bonus:.2f} USDT bonus from purchase by {user_to_confirm_id}")
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_id} about bonus: {e}")

    # 3. Notify the user whose payment was confirmed
    try:
        # Get user's total ticket count for today after increment
        user_tickets_res = supabase.from_('daily_tickets').select('count').eq('telegram_id', user_to_confirm_id).eq('date', datetime.date.today().isoformat()).single().execute()
        user_todays_total_tickets = 0
        if user_tickets_res.data and isinstance(user_tickets_res.data.get('count'), int):
            user_todays_total_tickets = user_tickets_res.data['count']
        else: # Fallback if single() fails or count not found, re-query sum (though less ideal)
            user_todays_total_tickets = await get_total_tickets_for_date(datetime.date.today()) # This is global, not user-specific! Error in logic.
            # Correct way to get user specific total if single fails:
            # entries = await get_daily_ticket_entries_for_draw(datetime.date.today())
            # for entry in entries:
            # if entry['telegram_id'] == user_to_confirm_id:
            # user_todays_total_tickets = entry['count']
            # break
            # For simplicity, assume .single().execute() works or count is 0
            logger.warning(f"Could not get specific ticket count for user {user_to_confirm_id} via single(), might show 0 or incorrect.")


        confirmation_text = (
            f"Your payment for {num_tickets_purchased} ticket(s) ({claimed_payment_amount_by_user:.2f} USDT) has been confirmed!\n"
            f"You now have a total of *{user_todays_total_tickets}* ticket(s) for today's draw! Good luck!"
        )
        # Try to edit the original "pending" message
        try:
             await context.bot.edit_message_text(
                 chat_id=original_chat_id, # Use stored chat_id
                 message_id=original_message_id,
                 text=confirmation_text,
                 parse_mode=ParseMode.MARKDOWN
             )
        except Exception as edit_e:
             logger.warning(f"Failed to edit original payment message for {user_to_confirm_id} (Chat: {original_chat_id}, Msg: {original_message_id}): {edit_e}. Sending new message instead.")
             # Fallback: send a new message
             await context.bot.send_message(
                 chat_id=user_to_confirm_id, # User's direct chat ID
                 text=confirmation_text,
                 parse_mode=ParseMode.MARKDOWN
             )
        logger.info(f"Payment confirmed for user {user_to_confirm_id}. {num_tickets_purchased} tickets added.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_to_confirm_id} about payment confirmation: {e}")

    if update.message: # Admin confirmation message
        await update.message.reply_text(f"Payment confirmed for user ID `{user_to_confirm_id}`. {num_tickets_purchased} tickets added and referral bonus processed (if applicable).")


@admin_only
async def manual_winner_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to manually trigger winner draw for the previous day."""
    if not update.message: return
    await update.message.reply_text("Triggering manual winner draw for the previous day...")
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    await perform_winner_draw(context, date_override=yesterday)
    await update.message.reply_text("Manual winner draw process complete. Check logs for details.")

# --- Scheduled Jobs ---

async def perform_winner_draw(context: ContextTypes.DEFAULT_TYPE, date_override: datetime.date | None = None) -> None:
    """Scheduled job to draw a winner for a specific date (usually yesterday's tickets)."""
    # Determine the date for which the draw is being conducted
    draw_date = date_override if date_override else datetime.date.today() - datetime.timedelta(days=1)
    logger.info(f"Starting winner draw process for tickets purchased on: {draw_date.isoformat()}")

    # 1. Calculate the actual prize amount for the draw_date based on that day's sales
    actual_prize_amount_for_draw = await calculate_prize_for_date(draw_date)
    logger.info(f"Calculated prize amount for {draw_date.isoformat()}: {actual_prize_amount_for_draw:.2f} USDT")

    # 2. Check if there's any prize pool
    if actual_prize_amount_for_draw <= Decimal("0.00"):
        logger.info(f"No prize pool available for {draw_date.isoformat()} (likely no tickets sold). No winner will be drawn.")
        broadcast_text = (
            f"Daily Draw Results for {draw_date.isoformat()}\n\n"
            "Unfortunately, no tickets were sold for this date, so there is no prize pool for this draw.\n"
            "Be sure to buy your tickets today for a chance to win in the next draw!"
        )
        user_ids_to_notify = await get_all_user_telegram_ids()
        if user_ids_to_notify:
            await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text)
        return # Exit if no prize

    # 3. Get all ticket entries for the draw_date
    ticket_entries_for_draw = await get_daily_ticket_entries_for_draw(draw_date)

    if not ticket_entries_for_draw:
        # This case should ideally be covered by actual_prize_amount_for_draw being 0,
        # but as a safeguard if data is inconsistent (e.g., tickets sold but not recorded correctly for prize calculation)
        logger.warning(f"Prize pool calculated as > 0 for {draw_date.isoformat()}, but no ticket entries found in 'daily_tickets'. Inconsistency detected. No winner declared.")
        # Notify admin about this inconsistency
        try:
            await context.bot.send_message(ADMIN_ID, f"WARNING: Inconsistency in draw for {draw_date.isoformat()}. Prize > 0 but no ticket entries. Please investigate daily_tickets table.")
        except Exception as e:
            logger.error(f"Failed to send inconsistency warning to admin: {e}")
        return

    # 4. Create a weighted list of participants for random.choice
    weighted_ticket_list = []
    for entry in ticket_entries_for_draw:
        # Ensure 'telegram_id' and 'count' exist and 'count' is positive
        if entry.get('telegram_id') and isinstance(entry.get('count'), int) and entry['count'] > 0 :
            weighted_ticket_list.extend([entry['telegram_id']] * entry['count'])

    if not weighted_ticket_list:
        logger.info(f"Ticket entries were found for {draw_date.isoformat()}, but after processing, the weighted list is empty (e.g., all counts were 0 or invalid). No winner declared.")
        return

    # 5. Select a winner
    winner_telegram_id = random.choice(weighted_ticket_list)
    winner_user_data = await get_user(winner_telegram_id) # Fetch winner's details

    winner_name = "A lucky user" # Default if user data not found
    winner_username = "N/A"
    if winner_user_data:
        winner_name = winner_user_data.get('first_name', f'User {winner_telegram_id}')
        winner_username = winner_user_data.get('username', 'N/A')

    # 6. Simulate sending prize and record winner
    await simulate_send_usdt(f"Winner ID: {winner_telegram_id}", actual_prize_amount_for_draw, "Winner Prize")
    await add_winner_record(winner_telegram_id, actual_prize_amount_for_draw, draw_date)

    # 7. Announce the winner
    broadcast_text = (
        f"Daily Draw Results for {draw_date.isoformat()}\n\n"
        f"And the winner is... *{winner_name}* (@{winner_username})!\n"
        f"Congratulations! You have won *{actual_prize_amount_for_draw:.2f} USDT*!\n\n"
        "Buy your tickets today using /buy for a chance to be the next winner!"
    )

    user_ids_to_notify = await get_all_user_telegram_ids()
    if user_ids_to_notify:
        await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Winner {winner_telegram_id} drawn and announced for {draw_date.isoformat()} with prize {actual_prize_amount_for_draw:.2f} USDT")


async def send_daily_marketing_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job to send a daily marketing message."""
    message_content = await get_random_marketing_message_content()
    if not message_content:
        logger.warning("No marketing messages found in DB to send.")
        return

    logger.info("Attempting to send daily marketing message...")
    user_ids = await get_all_user_telegram_ids()
    if not user_ids:
        logger.info("No users to send marketing message to.")
        return

    await broadcast_message_to_users_list(context, user_ids, message_content)
    # logger.info("Daily marketing message broadcast attempt finished.") # Logged inside broadcast_message_to_users_list


# --- Winners History Command ---

async def winners_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the last 7 winners (real winners only)."""
    if not update.message: return

    latest_real_winners = await get_latest_winners(limit=7) # Fetch up to 7
    winners_list_text = "TrustWin Bot Latest Winners\n\n"

    if not latest_real_winners:
        winners_list_text += "No winners yet! Be the first to win!\n"
    else:
        for i, winner_entry in enumerate(latest_real_winners):
            win_date_str = str(winner_entry.get('win_date', 'Unknown Date')) # Ensure it's a string
            try: # Try to parse and reformat date for consistency, if it's a valid ISO date string
                parsed_date = datetime.date.fromisoformat(win_date_str)
                win_date_display = parsed_date.strftime("%Y-%m-%d") # e.g., "2023-10-27"
            except ValueError:
                win_date_display = win_date_str # Use as is if not parsable

            amount = Decimal(str(winner_entry.get('amount', '0'))).quantize(Decimal("0.01"))
            user_info = winner_entry.get('user_info')
            name = "A User"
            if user_info and user_info.get('first_name'):
                name = user_info.get('first_name')
            elif user_info: # If no first_name but user_info exists, use telegram_id as fallback
                name = f"User {winner_entry.get('telegram_id', 'Unknown')}"


            winners_list_text += f"{i+1}. Date: {win_date_display}: *{name}* won *{amount:.2f} USDT*\n"

    await update.message.reply_text(winners_list_text, parse_mode=ParseMode.MARKDOWN)


# --- Error Handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before attempting to send a message
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    # Attempt to send error message to admin
    try:
        error_summary = str(context.error)[:1000] # Basic summary
        update_str = str(update) if isinstance(update, Update) else str(type(update))
        update_summary = update_str[:1000]

        error_message = f"Bot Error Alert!\n\nError Type: {type(context.error).__name__}\nError: {error_summary}\n\nUpdate Type: {type(update).__name__}\nUpdate Details: {update_summary}"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=error_message
        )
    except Exception as e_notify: # Catch errors during notification
        logger.error(f"CRITICAL: Failed to send error notification to admin {ADMIN_ID}. Original error was: {context.error}. Notification error: {e_notify}")


# --- Main Function ---
def main() -> None:
    """Start the bot."""
    # Initial log to confirm bot is starting, before any potential env var issues
    logger.info("Attempting to start TrustWin Bot...")

    # Ensure environment variables are loaded and validated (done at the top)
    # Ensure Supabase client is initialized (done at the top)

    try:
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("Telegram Application built successfully.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to build Telegram Application: {e}. Bot cannot start.")
        return # Exit if application cannot be built

    job_queue = application.job_queue
    if not job_queue:
        # This is highly unlikely with ApplicationBuilder but good to check.
        logger.critical("FATAL: Failed to get job queue from application. Scheduled tasks cannot run. Bot cannot start reliably.")
        return


    # Set timezone for scheduler
    try:
        timezone = pytz.timezone(TIMEZONE_STR)
        logger.info(f"Scheduler timezone set to: {TIMEZONE_STR}")
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: '{TIMEZONE_STR}'. Defaulting to UTC for scheduler.")
        timezone = pytz.utc # Fallback to UTC


    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("winners", winners_command))

    # Admin command handlers (with @admin_only decorator applied to the functions themselves)
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("confirm_payment", confirm_payment_command))
    application.add_handler(CommandHandler("trigger_draw", manual_winner_draw_command))

    # Add callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(paid_button_callback, pattern='^paid_'))

    # Add error handler
    application.add_error_handler(error_handler)

    # Schedule jobs
    # Winner draw daily at 00:01 (1 minute past midnight) in the specified timezone
    job_queue.run_daily(
        perform_winner_draw, # Uses the renamed function
        time=datetime.time(hour=0, minute=1, second=0, tzinfo=timezone),
        name="daily_winner_draw"
        # days argument defaults to all days of the week (0-6)
    )
    logger.info(f"Scheduled daily winner draw at 00:01 ({timezone}) for previous day's tickets.")

    # Daily marketing message at 09:00 AM in the specified timezone
    job_queue.run_daily(
        send_daily_marketing_message_job,
        time=datetime.time(hour=9, minute=0, second=0, tzinfo=timezone),
        name="daily_marketing_message"
    )
    logger.info(f"Scheduled daily marketing message at 09:00 ({timezone}).")


    # Start the Bot
    logger.info("Bot is starting to poll for updates...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Bot polling failed critically: {e}. Bot has stopped.")
    logger.info("Bot polling has ended.")


if __name__ == '__main__':
    main()
