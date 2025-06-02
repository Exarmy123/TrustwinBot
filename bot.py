# bot.py

import os
import logging
import asyncio
import random
import datetime
from decimal import Decimal

# from dotenv import load_dotenv # Uncomment if using a .env file locally

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from supabase.client import create_client, Client # supabase-py v1.x.x
# from postgrest import APIError as PostgrestAPIError # For more specific error handling if needed

import pytz

# --- Environment Variables ---
# load_dotenv() # Uncomment if using a .env file

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
USDT_WALLET = os.getenv("USDT_WALLET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TICKET_PRICE_USDT_STR = os.getenv("TICKET_PRICE_USDT", "1.0")
REFERRAL_PERCENT_STR = os.getenv("REFERRAL_PERCENT", "0.5") # 0.5 for 50%
WINNER_AMOUNT_USDT_STR = os.getenv("WINNER_AMOUNT_USDT", "5.0")
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Kolkata") # Default to IST

# Validate and convert environment variables
if not all([BOT_TOKEN, ADMIN_ID_STR, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY]):
    logging.error("FATAL: Missing required environment variables (BOT_TOKEN, ADMIN_ID, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY)!")
    exit(1)

try:
    ADMIN_ID = int(ADMIN_ID_STR)
    TICKET_PRICE_USDT = Decimal(TICKET_PRICE_USDT_STR)
    REFERRAL_PERCENT = Decimal(REFERRAL_PERCENT_STR)
    WINNER_AMOUNT_USDT = Decimal(WINNER_AMOUNT_USDT_STR)
except ValueError as e:
    logging.error(f"FATAL: Invalid format for numeric environment variables (ADMIN_ID, TICKET_PRICE_USDT, REFERRAL_PERCENT, WINNER_AMOUNT_USDT): {e}")
    exit(1)

# --- Supabase Client ---
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logging.error(f"FATAL: Could not initialize Supabase client: {e}")
    exit(1)

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Global State (for pending payments - Simple in-memory approach) ---
# WARNING: In a multi-instance setup, this should be persistent (e.g., Redis or DB)
pending_payments = {} # {user_id: {amount: Decimal, message_id: int, date: date, chat_id: int}}

# --- Helper Functions: Database ---

async def get_user(telegram_id: int):
    """Fetch a user from the database by telegram_id."""
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).single().execute()
        return response.data
    except Exception as e: # Catches PostgrestAPIError if .single() finds no or multiple rows
        if "PGRST116" in str(e): # PGRST116: "JWSError JWSInvalidSignature" or "JWSError JWTokenInvalid"
             logger.warning(f"Supabase query for user {telegram_id} failed, likely no user found or multiple (should not happen with .single() and unique telegram_id). Error: {e}")
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
        logger.error(f"Supabase error creating user {telegram_id}: {response.error.message if response.error else 'Unknown error'}")
        return None
    except Exception as e:
        logger.error(f"Exception creating user {telegram_id}: {e}")
        return None

async def increment_daily_tickets(telegram_id: int, count: int = 1): # count param might be unused if RPC always increments by 1
    """Increment ticket count for a user for today's date using RPC."""
    try:
        today = datetime.date.today().isoformat()
        response = supabase.rpc('increment_daily_ticket', {'user_id_input': telegram_id, 'ticket_date_input': today}).execute() # Ensure RPC param names match
        if response.error:
             logger.error(f"Supabase RPC error incrementing tickets for {telegram_id} on {today}: {response.error.message}")
             return False
        logger.info(f"Tickets incremented via RPC for user {telegram_id} for {today}.")
        return True
    except Exception as e:
        logger.error(f"Exception incrementing tickets for {telegram_id}: {e}")
        return False

async def get_daily_ticket_counts(date_obj: datetime.date):
    """Get aggregated ticket counts for a specific date."""
    try:
        response = supabase.from_('daily_tickets').select('telegram_id, count').eq('date', date_obj.isoformat()).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Supabase error fetching daily tickets for {date_obj}: {e}")
        return []

async def add_winner(telegram_id: int, amount: Decimal, win_date: datetime.date):
    """Add a winner entry to the database."""
    try:
        data_to_insert = {
            'telegram_id': telegram_id,
            'amount': float(amount), # Supabase numeric often maps to float
            'win_date': win_date.isoformat()
        }
        response = supabase.from_('winners').insert([data_to_insert]).execute()
        if response.data:
            logger.info(f"Winner recorded: {telegram_id} on {win_date} with {amount} USDT")
            return response.data[0]
        logger.error(f"Supabase error adding winner {telegram_id}: {response.error.message if response.error else 'Unknown error'}")
        return None
    except Exception as e:
        logger.error(f"Exception adding winner {telegram_id}: {e}")
        return None

async def get_latest_winners(limit: int):
    """Fetch the latest winners from the database, including user info."""
    try:
        winners_response = supabase.from_('winners').select('telegram_id, amount, win_date').order('win_date', desc=True).limit(limit).execute()
        if not winners_response.data:
            return []

        winner_telegram_ids = [w['telegram_id'] for w in winners_response.data]
        if not winner_telegram_ids:
            return winners_response.data # Should not happen if winners_response.data is not empty

        users_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', winner_telegram_ids).execute()
        user_map = {user['telegram_id']: user for user in users_response.data} if users_response.data else {}

        for winner in winners_response.data:
            winner['user_info'] = user_map.get(winner['telegram_id'])
        return winners_response.data
    except Exception as e:
        logger.error(f"Supabase error fetching latest winners: {e}")
        return []

async def get_all_user_telegram_ids():
    """Fetch all user telegram_ids for broadcasting."""
    try:
        response = supabase.from_('users').select('telegram_id').execute()
        return [user['telegram_id'] for user in response.data] if response.data else []
    except Exception as e:
        logger.error(f"Supabase error fetching all user telegram_ids: {e}")
        return []

async def get_total_users_count():
    """Get the total count of users."""
    try:
        # Using PostgREST's count header
        response = supabase.from_('users').select('telegram_id', count='exact').limit(0).execute() # Fetch no data, just count
        return response.count if response.count is not None else 0
    except Exception as e:
        logger.error(f"Supabase error fetching total users count: {e}")
        return 0

async def get_todays_total_tickets_count():
    """Get the total ticket count for today."""
    try:
        today = datetime.date.today().isoformat()
        # Using PostgREST's aggregate functions
        response = supabase.from_('daily_tickets').select('count').eq('date', today).execute() # This gets all rows
        if response.data:
            return sum(item['count'] for item in response.data if item.get('count') is not None)
        return 0
    except Exception as e:
        logger.error(f"Supabase error fetching today's total tickets count: {e}")
        return 0


async def get_random_marketing_message_content():
    """Fetch a random marketing message from the database."""
    try:
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
    """Simulates sending USDT."""
    logger.info(f"SIMULATING USDT SEND: Type='{transaction_type}', Recipient='{recipient_info}', Amount='{amount:.2f} USDT'")
    await asyncio.sleep(random.uniform(0.5, 1.5)) # Simulate network delay
    logger.info(f"SIMULATION COMPLETE: USDT sent successfully (simulated).")
    return True # Assume success for simulation

# --- Message Broadcasting Helper ---
async def broadcast_message_to_users_list(context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str, parse_mode: str | None = None):
    """Helper to send a message to a list of user IDs concurrently."""
    sent_count = 0
    failed_count = 0
    tasks = []

    async def send_single_message(user_id_to_send: int):
        nonlocal sent_count, failed_count
        try:
            await context.bot.send_message(chat_id=user_id_to_send, text=text, parse_mode=parse_mode)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast message to user {user_id_to_send}: {e}")
            failed_count +=1

    for user_id in user_ids:
        tasks.append(send_single_message(user_id))

    if tasks:
        await asyncio.gather(*tasks)
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
    first_name = user.first_name or "User"
    last_name = user.last_name

    referrer_telegram_id = None
    if context.args:
        try:
            potential_referrer_id = int(context.args[0])
            if potential_referrer_id != telegram_id:
                referrer_user = await get_user(potential_referrer_id)
                if referrer_user:
                    referrer_telegram_id = potential_referrer_id
                    logger.info(f"User {telegram_id} started with referrer {referrer_telegram_id}")
                else:
                    logger.warning(f"User {telegram_id} used invalid referrer ID: {context.args[0]}")
            else:
                 logger.warning(f"User {telegram_id} tried to refer themselves.")
        except (ValueError, IndexError):
            logger.warning(f"User {telegram_id} used invalid referral link format: {context.args}")

    db_user = await get_user(telegram_id)
    is_new_user = db_user is None

    welcome_message = (
        f"Hello {first_name}! Welcome to TrustWin Bot!\n\n"
        "Get your tickets daily for a chance to win big in our USDT lottery!\n\n"
    )

    if is_new_user:
        created_user = await create_user(telegram_id, username, first_name, last_name, referrer_telegram_id)
        if created_user:
            welcome_message += "You've been registered! Thanks for joining.\n"
            if referrer_telegram_id:
                try:
                    referrer_display_name = first_name
                    if username:
                        referrer_display_name += f" (@{username})"
                    else:
                        referrer_display_name += f" (ID: {telegram_id})"

                    await context.bot.send_message(
                        chat_id=referrer_telegram_id,
                        text=f"Great news! Your referral {referrer_display_name} has joined TrustWin Bot using your link!\n"
                             f"You'll earn {REFERRAL_PERCENT*100:.0f}% of the ticket price every time they buy a ticket!"
                    )
                    logger.info(f"Notified referrer {referrer_telegram_id} about new user {telegram_id}")
                except Exception as e:
                    logger.warning(f"Could not notify referrer {referrer_telegram_id}: {e}")
        else:
            welcome_message += "There was an issue registering you. Please try /start again later.\n"


    welcome_message += (
        f"The prize amount for today's draw is *{WINNER_AMOUNT_USDT:.2f} USDT*.\n"
        f"Each ticket costs *{TICKET_PRICE_USDT:.2f} USDT*.\n\n"
        "Use the /buy command to get your ticket(s)!\n\n"
        f"Want to earn passively? Share your unique referral link:\n"
        f"`https://t.me/{context.bot.username}?start={telegram_id}`\n"
        f"You get {REFERRAL_PERCENT*100:.0f}% of the ticket price for every ticket your referred friends buy, FOREVER!\n\n"
        "May the odds be ever in your favor!"
    )

    if update.message:
        await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
    else:
        logger.warning("Start command invoked without a message attribute in update.")


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /buy command to initiate ticket purchase."""
    user = update.effective_user
    if not user:
        logger.warning("Buy command received without an effective_user.")
        return

    telegram_id = user.id

    db_user = await get_user(telegram_id)
    if not db_user:
        if update.message:
            await update.message.reply_text("Please use the /start command first to register.")
        return

    ticket_amount = TICKET_PRICE_USDT # Assuming 1 ticket per purchase flow

    keyboard = [
        [InlineKeyboardButton("I have paid", callback_data=f"paid_{ticket_amount}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        f"To buy one ticket for *{ticket_amount:.2f} USDT*:\n\n"
        f"1. Send exactly *{ticket_amount:.2f} USDT (TRC-20)* to the following wallet address:\n"
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
    if not query or not query.message:
        logger.error("paid_button_callback received invalid query object.")
        return

    user = query.effective_user
    if not user:
        logger.error("paid_button_callback received query without an effective_user.")
        await query.answer("Error: Could not identify user.", show_alert=True)
        return

    telegram_id = user.id
    data = query.data

    await query.answer("Processing your payment confirmation...")

    try:
        amount_str = data.split('_')[1]
        claimed_amount = Decimal(amount_str)
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid payment confirmation data. Please try /buy again.")
        logger.error(f"Invalid callback data received: {data} from user {telegram_id}")
        return

    pending_payments[telegram_id] = {
        'amount': claimed_amount,
        'date': datetime.date.today(),
        'message_id': query.message.message_id,
        'chat_id': query.message.chat_id # Store chat_id for editing
    }

    admin_notification_text = (
        f"Payment Claimed!\n\n"
        f"User: {user.first_name or 'N/A'} (@{user.username or 'N/A'}) [ID: `{telegram_id}`]\n"
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
            f"Received your payment confirmation for {claimed_amount:.2f} USDT.\n"
            "Please wait while the admin verifies the transaction. Your tickets will be added shortly!"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin {ADMIN_ID} or edit user message: {e}")
        # User message might have already been edited if admin notification failed later
        # So, try to send a new message to user if edit fails or hasn't happened.
        try:
            await context.bot.send_message(
                chat_id=telegram_id, # Send directly to user if edit failed
                text=f"Received your payment confirmation for {claimed_amount:.2f} USDT.\n"
                     "There was an issue during processing, but your claim is recorded. Please wait for verification."
            )
        except Exception as e_user_notify:
            logger.error(f"Also failed to send direct notification to user {telegram_id}: {e_user_notify}")


# --- Admin Decorator ---
def admin_only(handler):
    """Decorator to restrict handlers to admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("You are not authorized to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("You are not authorized.", show_alert=True)
            return
        await handler(update, context)
    return wrapper

# --- Admin Commands ---

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to show bot statistics."""
    total_users = await get_total_users_count()
    todays_tickets = await get_todays_total_tickets_count()
    pending_count = len(pending_payments)

    stats_text = (
        "Bot Statistics\n\n"
        f"Total Users: `{total_users}`\n"
        f"Today's Tickets: `{todays_tickets}`\n"
        f"Pending Payments (Admin Verification): `{pending_count}`"
    )
    if update.message:
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list active users (first 50)."""
    all_user_ids = await get_all_user_telegram_ids()

    if not all_user_ids:
        if update.message: await update.message.reply_text("No users found.")
        return

    user_list_text = "Active Users\n\n"
    display_limit = 50
    limited_user_ids = all_user_ids[:display_limit]

    if len(all_user_ids) > display_limit:
        user_list_text += f"Listing first {display_limit} of {len(all_user_ids)} users:\n"

    user_details_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', limited_user_ids).execute()
    user_details = user_details_response.data if user_details_response.data else []

    for user_data in user_details:
        name = user_data.get('first_name', 'N/A')
        username = user_data.get('username')
        user_id = user_data.get('telegram_id')
        user_list_text += f"- {name} (@{username or 'N/A'}) [ID: `{user_id}`]\n"

    if update.message:
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
    await broadcast_message_to_users_list(context, all_user_ids, message_text)
    if update.message: await update.message.reply_text("Broadcast finished. Check logs for details.")


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

    payment_info = pending_payments.pop(user_to_confirm_id)
    claimed_amount = payment_info['amount']
    # payment_date = payment_info['date'] # Date is implicitly today for increment_daily_tickets
    original_message_id = payment_info['message_id']
    original_chat_id = payment_info['chat_id']

    # --- Process Confirmation ---
    # 1. Increment tickets
    if not await increment_daily_tickets(user_to_confirm_id):
        logger.error(f"Failed to increment tickets for {user_to_confirm_id} after payment confirmation.")
        # Potentially re-add to pending_payments or handle error
        if update.message: await update.message.reply_text(f"Error: Failed to increment tickets for user {user_to_confirm_id}. Payment not fully processed. Check logs.")
        return

    # 2. Handle Referral Bonus
    referred_user_data = await get_user(user_to_confirm_id)
    if referred_user_data and referred_user_data.get('referrer_telegram_id'):
        referrer_id = referred_user_data['referrer_telegram_id']
        referral_bonus = claimed_amount * REFERRAL_PERCENT
        if referral_bonus > 0:
            referrer_info_str = f"Referrer ID: {referrer_id} (Address needed for real payout)"
            await simulate_send_usdt(referrer_info_str, referral_bonus, "Referral Bonus")
            try:
                referred_user_name = referred_user_data.get('first_name', f'User {user_to_confirm_id}')
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"Referral Bonus Received!\n\n"
                         f"You earned *{referral_bonus:.2f} USDT* because your referral {referred_user_name} bought a ticket!\n"
                         "Keep sharing your link to earn more!",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified referrer {referrer_id} of bonus from {user_to_confirm_id}")
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_id} about bonus: {e}")

    # 3. Notify the user
    try:
        # Get user's ticket count for today
        user_tickets_res = supabase.from_('daily_tickets').select('count').eq('telegram_id', user_to_confirm_id).eq('date', datetime.date.today().isoformat()).single().execute()
        user_todays_count = user_tickets_res.data['count'] if user_tickets_res.data and user_tickets_res.data.get('count') is not None else 0

        confirmation_text = (
            f"Your payment of {claimed_amount:.2f} USDT has been confirmed!\n"
            f"You now have *{user_todays_count}* ticket(s) for today's draw! Good luck!"
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
             logger.warning(f"Failed to edit original payment message for {user_to_confirm_id} (Chat: {original_chat_id}, Msg: {original_message_id}): {edit_e}. Sending new message.")
             await context.bot.send_message(
                 chat_id=user_to_confirm_id, # Fallback to user's direct chat
                 text=confirmation_text,
                 parse_mode=ParseMode.MARKDOWN
             )
        logger.info(f"Payment confirmed for user {user_to_confirm_id}. Tickets added.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_to_confirm_id} about payment confirmation: {e}")

    if update.message:
        await update.message.reply_text(f"Payment confirmed for user ID `{user_to_confirm_id}`. Tickets added and referral bonus processed (if applicable).")


@admin_only
async def manual_winner_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to manually trigger winner draw for the previous day."""
    if update.message: await update.message.reply_text("Triggering manual winner draw for the previous day...")
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    await draw_winner_for_date(context, date_override=yesterday)
    if update.message: await update.message.reply_text("Manual winner draw process complete. Check logs.")

# --- Scheduled Jobs ---

async def draw_winner_for_date(context: ContextTypes.DEFAULT_TYPE, date_override: datetime.date | None = None) -> None:
    """Scheduled job to draw a winner for a specific date (usually yesterday)."""
    draw_date = date_override if date_override else datetime.date.today() - datetime.timedelta(days=1)
    logger.info(f"Starting winner draw for tickets purchased on {draw_date.isoformat()}")

    ticket_entries = await get_daily_ticket_counts(draw_date)

    if not ticket_entries:
        logger.info(f"No tickets bought on {draw_date.isoformat()}. No winner.")
        broadcast_text = (
            f"Daily Draw Results for {draw_date.isoformat()}\n\n"
            "Looks like no one bought tickets for this date.\n"
            "No winner for this draw. Buy tickets today for a chance to win tomorrow!"
        )
        user_ids_to_notify = await get_all_user_telegram_ids()
        if user_ids_to_notify:
            await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text)
        return

    ticket_list = []
    for entry in ticket_entries:
        if entry.get('telegram_id') and entry.get('count', 0) > 0 :
            ticket_list.extend([entry['telegram_id']] * entry['count'])

    if not ticket_list:
        logger.info(f"Ticket entries found for {draw_date.isoformat()}, but processed list is empty. No winner.")
        # This case should ideally not happen if ticket_entries is not empty and has valid data
        return

    winner_telegram_id = random.choice(ticket_list)
    winner_user_data = await get_user(winner_telegram_id)
    winner_name = "A lucky user"
    winner_username = "N/A"

    if winner_user_data:
        winner_name = winner_user_data.get('first_name', f'User {winner_telegram_id}')
        winner_username = winner_user_data.get('username', 'N/A')

    await simulate_send_usdt(f"Winner ID: {winner_telegram_id}", WINNER_AMOUNT_USDT, "Winner Prize")
    await add_winner(winner_telegram_id, WINNER_AMOUNT_USDT, draw_date)

    broadcast_text = (
        f"Daily Draw Results for {draw_date.isoformat()}\n\n"
        f"And the winner is... *{winner_name}* (@{winner_username})!\n"
        f"Congratulations! You have won *{WINNER_AMOUNT_USDT:.2f} USDT*!\n\n"
        "Buy your tickets today using /buy for a chance to be the next winner!"
    )

    user_ids_to_notify = await get_all_user_telegram_ids()
    if user_ids_to_notify:
        await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Winner {winner_telegram_id} drawn and announced for {draw_date.isoformat()}")


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
    logger.info("Daily marketing message broadcast attempt finished.")


# --- Winners History Command ---

async def winners_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the last 7 winners (real + "filler" to always show 7 entries)."""
    if not update.message: return

    latest_real_winners = await get_latest_winners(7)
    num_real_winners = len(latest_real_winners)

    winners_list_text = "TrustWin Bot Latest Winners\n\n"

    all_winners_display = []

    # Add real winners
    for rw in latest_real_winners:
        rw_date = rw.get('win_date')
        # Parse date string to datetime.date object if it's a string
        if isinstance(rw_date, str):
            try:
                rw_date = datetime.date.fromisoformat(rw_date)
            except ValueError:
                logger.warning(f"Could not parse win_date string: {rw_date} for real winner. Skipping.")
                continue
        elif not isinstance(rw_date, datetime.date):
             logger.warning(f"Win_date is not a string or date object: {rw_date} for real winner. Skipping.")
             continue


        all_winners_display.append({
            'date': rw_date,
            'amount': Decimal(str(rw.get('amount', '0'))), # Ensure Decimal
            'name': rw.get('user_info', {}).get('first_name', 'A User'),
            'is_real': True
        })

    # Generate "filler" winners if needed, to show 7 total
    num_fillers_needed = 7 - len(all_winners_display)
    fake_names = ["Alex", "Bella", "Chris", "Dana", "Eddie", "Fiona", "George"]
    fake_amounts = [Decimal("2.5"), Decimal("5.0"), Decimal("3.0"), Decimal("7.0")]

    # Determine start date for fillers
    if all_winners_display:
        # Sort by date to find the earliest real winner shown
        all_winners_display.sort(key=lambda x: x['date'])
        last_shown_date = all_winners_display[0]['date'] # Earliest date among real winners
    else:
        last_shown_date = datetime.date.today() # If no real winners, start from today

    for i in range(num_fillers_needed):
        # Fillers go to dates before the last_shown_date or further back if no real winners
        filler_date = last_shown_date - datetime.timedelta(days=i + 1)
        all_winners_display.append({
            'date': filler_date,
            'amount': random.choice(fake_amounts),
            'name': random.choice(fake_names),
            'is_real': False
        })

    # Sort all display entries by date descending
    all_winners_display.sort(key=lambda x: x['date'], reverse=True)

    if not all_winners_display:
        winners_list_text += "No winners to display yet! Be the first!\n"
    else:
        for entry in all_winners_display[:7]: # Ensure we only show 7
            name_display = f"*{entry['name']}*"
            if not entry['is_real']:
                 name_display = f"_{entry['name']}_" # Italic for fillers

            winners_list_text += f"Date: {entry['date'].isoformat()}: {name_display} won *{entry['amount']:.2f} USDT*\n"

    await update.message.reply_text(winners_list_text, parse_mode=ParseMode.MARKDOWN)


# --- Error Handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    # Send error message to admin
    try:
        error_summary = str(context.error)[:1000] # Basic summary
        update_summary = str(update)[:1000] if update else "Update object is None"

        error_message = f"Bot Error Alert!\n\nError: {error_summary}\n\nUpdate: {update_summary}"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=error_message
        )
    except Exception as e:
        logger.error(f"CRITICAL: Failed to send error notification to admin {ADMIN_ID}: {e}")

# --- Main Function ---
def main() -> None:
    """Start the bot."""
    logger.info("Starting TrustWin Bot...")

    try:
        application = Application.builder().token(BOT_TOKEN).build()
    except Exception as e:
        logger.critical(f"Failed to build Telegram Application: {e}")
        return # Cannot proceed

    job_queue = application.job_queue
    if not job_queue:
        logger.critical("Failed to get job queue from application. Scheduler will not work.")
        # Decide if you want to exit or run without scheduler
        # exit(1)


    # Set timezone for scheduler
    try:
        timezone = pytz.timezone(TIMEZONE_STR)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: '{TIMEZONE_STR}'. Defaulting to UTC for scheduler.")
        timezone = pytz.utc


    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("winners", winners_command))

    # Admin command handlers
    application.add_handler(CommandHandler("stats", stats_command)) # @admin_only applied directly
    application.add_handler(CommandHandler("users", users_command)) # @admin_only applied directly
    application.add_handler(CommandHandler("broadcast", broadcast_command)) # @admin_only applied directly
    application.add_handler(CommandHandler("confirm_payment", confirm_payment_command)) # @admin_only applied directly
    application.add_handler(CommandHandler("trigger_draw", manual_winner_draw_command)) # Renamed for clarity, @admin_only applied

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(paid_button_callback, pattern='^paid_'))

    # Add error handler
    application.add_error_handler(error_handler)

    # Schedule jobs (ensure job_queue exists)
    if job_queue:
        # Winner draw daily at 12:01 AM specified timezone
        job_queue.run_daily(
            draw_winner_for_date, # Renamed function
            time=datetime.time(hour=0, minute=1, second=0, tzinfo=timezone),
            name="daily_winner_draw"
            # days argument defaults to all days (0-6)
        )
        logger.info(f"Scheduled daily winner draw at 00:01 {timezone}")

        # Daily marketing message at 9:00 AM specified timezone
        job_queue.run_daily(
            send_daily_marketing_message_job, # Renamed function
            time=datetime.time(hour=9, minute=0, second=0, tzinfo=timezone),
            name="daily_marketing_message"
        )
        logger.info(f"Scheduled daily marketing message at 09:00 {timezone}")
    else:
        logger.warning("Job queue not available. Scheduled tasks will not run.")


    logger.info("Bot is starting to poll...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Bot polling failed critically: {e}")

if __name__ == '__main__':
    main()
