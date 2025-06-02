# bot.py

import os
import logging # logging को पहले इम्पोर्ट करें
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

# --- Logging Configuration (इसे एनवायरनमेंट वेरिएबल लोड होने के ठीक बाद रखें) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__) # logger को यहाँ डिफाइन करें

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


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# +++ यहाँ डिबगिंग कोड डाला गया है +++
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
logger.info("--- STARTING ENV VAR CHECK (DEBUG) ---")
logger.info(f"BOT_TOKEN is set: {bool(BOT_TOKEN)}")
logger.info(f"ADMIN_ID_STR is set: {bool(ADMIN_ID_STR)}")
logger.info(f"USDT_WALLET is set: {bool(USDT_WALLET)}")
logger.info(f"SUPABASE_URL is set: {bool(SUPABASE_URL)}")
logger.info(f"SUPABASE_KEY is set: {bool(SUPABASE_KEY)}")
# आप चाहें तो वैकल्पिक वेरिएबल्स को भी चेक कर सकते हैं
logger.info(f"TICKET_PRICE_USDT_STR is set: {bool(TICKET_PRICE_USDT_STR)}")
logger.info(f"REFERRAL_PERCENT_STR is set: {bool(REFERRAL_PERCENT_STR)}")
logger.info(f"GLOBAL_CRYPTO_TAX_PERCENT_STR is set: {bool(GLOBAL_CRYPTO_TAX_PERCENT_STR)}")
logger.info(f"TIMEZONE_STR is set: {bool(TIMEZONE_STR)}")
logger.info("--- FINISHED ENV VAR CHECK (DEBUG) ---")
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# +++ डिबगिंग कोड का अंत +++
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


# Validate and convert environment variables
if not all([BOT_TOKEN, ADMIN_ID_STR, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY]):
    logger.error("FATAL: Missing required core environment variables!")
    # --- कौन सा खास वेरिएबल गायब है, यह देखने के लिए और डिबगिंग ---
    if not BOT_TOKEN: logger.error("DEBUG CHECK: BOT_TOKEN specifically is missing or empty.")
    if not ADMIN_ID_STR: logger.error("DEBUG CHECK: ADMIN_ID_STR (for ADMIN_ID key) specifically is missing or empty.")
    if not USDT_WALLET: logger.error("DEBUG CHECK: USDT_WALLET specifically is missing or empty.")
    if not SUPABASE_URL: logger.error("DEBUG CHECK: SUPABASE_URL specifically is missing or empty.")
    if not SUPABASE_KEY: logger.error("DEBUG CHECK: SUPABASE_KEY specifically is missing or empty.")
    # --- डिबगिंग का अंत ---
    exit(1) # बॉट को यहाँ बंद कर दें अगर मुख्य वेरिएबल्स नहीं हैं

try:
    ADMIN_ID = int(ADMIN_ID_STR)
    TICKET_PRICE_USDT = Decimal(TICKET_PRICE_USDT_STR)
    REFERRAL_PERCENT = Decimal(REFERRAL_PERCENT_STR)
    GLOBAL_CRYPTO_TAX_PERCENT = Decimal(GLOBAL_CRYPTO_TAX_PERCENT_STR)

    if not (Decimal(0) <= REFERRAL_PERCENT <= Decimal(1)):
        logger.error("FATAL: REFERRAL_PERCENT must be between 0 and 1 (e.g., 0.25 for 25%).")
        exit(1)
    if not (Decimal(0) <= GLOBAL_CRYPTO_TAX_PERCENT <= Decimal(1)):
        logger.error("FATAL: GLOBAL_CRYPTO_TAX_PERCENT must be between 0 and 1 (e.g., 0.25 for 25%).")
        exit(1)
    if (REFERRAL_PERCENT + GLOBAL_CRYPTO_TAX_PERCENT) > Decimal(1):
        logger.error("FATAL: Sum of REFERRAL_PERCENT and GLOBAL_CRYPTO_TAX_PERCENT cannot exceed 1 (100%).")
        exit(1)

except ValueError as e:
    logger.error(f"FATAL: Invalid format for numeric environment variables (ADMIN_ID, TICKET_PRICE_USDT, REFERRAL_PERCENT, GLOBAL_CRYPTO_TAX_PERCENT): {e}")
    exit(1)

# Calculate Prize Pool Contribution Percentage
PRIZE_POOL_CONTRIBUTION_PERCENT = Decimal(1) - REFERRAL_PERCENT - GLOBAL_CRYPTO_TAX_PERCENT
if PRIZE_POOL_CONTRIBUTION_PERCENT < Decimal(0):
    logger.error("FATAL: Prize pool contribution percentage is negative. Check referral and tax percentages.")
    exit(1)

# लॉगिंग को यहाँ करें, जब सभी वेरिएबल्स प्रोसेस हो चुके हों
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

# --- Global State (for pending payments - Simple in-memory approach) ---
pending_payments = {} # {user_id: {amount_paid: Decimal, num_tickets: int, message_id: int, date: date, chat_id: int}}

# --- Helper Functions: Database ---

async def get_user(telegram_id: int):
    """Fetch a user from the database by telegram_id."""
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).single().execute()
        return response.data
    except Exception as e:
        if hasattr(e, 'message') and "PGRST116" in e.message and "0 rows" in e.message:
            logger.debug(f"Supabase: User {telegram_id} not found (0 rows for single()).")
        elif hasattr(e, 'code') and e.code == 'PGRST116':
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
        error_msg = "Unknown error"
        if response.error:
            error_msg = response.error.message
            if hasattr(response.error, 'details'):
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
        response = supabase.rpc('increment_daily_ticket', {
            'user_id_input': telegram_id,
            'ticket_date_input': today_iso,
            'num_tickets_to_add': num_tickets
        }).execute()

        if hasattr(response, 'error') and response.error:
             logger.error(f"Supabase RPC error incrementing {num_tickets} tickets for {telegram_id} on {today_iso}: {response.error.message}")
             return False
        # For supabase-py v2, a successful void RPC might return None or no error attribute.
        # If an error occurs, it should ideally raise an exception or set response.error.
        # The check above handles explicit .error. If it passes, assume success.
        logger.info(f"{num_tickets} tickets incremented via RPC for user {telegram_id} for {today_iso}.")
        return True
    except Exception as e:
        logger.error(f"Exception calling RPC increment_daily_ticket for user {telegram_id} ({num_tickets} tickets): {e}")
        return False


async def get_total_tickets_for_date(date_obj: datetime.date) -> int:
    """Get the total number of tickets sold on a specific date."""
    try:
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
            'amount': float(amount),
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
        users_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', winner_telegram_ids).execute()
        user_map = {user['telegram_id']: user for user in users_response.data} if users_response.data else {}
        for winner in winners_response.data:
            winner['user_info'] = user_map.get(winner['telegram_id'])
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
        response = supabase.from_('users').select('telegram_id', count='exact').limit(0).execute()
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
    logger.info(f"Total tickets sold on {date_obj.isoformat()} for prize calculation: {total_tickets_sold_on_date}")
    if total_tickets_sold_on_date == 0:
        return Decimal("0.00")
    total_revenue_from_tickets = total_tickets_sold_on_date * TICKET_PRICE_USDT
    prize_amount = total_revenue_from_tickets * PRIZE_POOL_CONTRIBUTION_PERCENT
    return prize_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# --- Helper Functions: USDT Simulation & Broadcast ---
async def simulate_send_usdt(recipient_info: str, amount: Decimal, transaction_type: str):
    logger.info(f"SIMULATING USDT SEND: Type='{transaction_type}', Recipient='{recipient_info}', Amount='{amount:.2f} USDT'")
    await asyncio.sleep(random.uniform(0.5, 1.2))
    logger.info(f"SIMULATION COMPLETE: USDT sent successfully (simulated).")
    return True

async def broadcast_message_to_users_list(context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str, parse_mode: str | None = None):
    sent_count = 0; failed_count = 0; tasks = []
    async def send_single_message(user_id_to_send: int):
        nonlocal sent_count, failed_count
        try:
            await context.bot.send_message(chat_id=user_id_to_send, text=text, parse_mode=parse_mode)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast message to user {user_id_to_send}: {e}"); failed_count +=1
    for user_id in user_ids: tasks.append(send_single_message(user_id))
    if tasks: await asyncio.gather(*tasks)
    logger.info(f"Broadcast attempt finished. Sent: {sent_count}, Failed: {failed_count} out of {len(user_ids)} users.")

# --- Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user;
    if not user: logger.warning("Start command received without an effective_user."); return
    telegram_id = user.id; username = user.username; first_name = user.first_name or "User"; last_name = user.last_name
    referrer_telegram_id = None
    if context.args:
        try:
            potential_referrer_id = int(context.args[0])
            if potential_referrer_id != telegram_id:
                referrer_user = await get_user(potential_referrer_id)
                if referrer_user: referrer_telegram_id = potential_referrer_id; logger.info(f"User {telegram_id} ({username or first_name}) started with referrer {referrer_telegram_id}")
                else: logger.warning(f"User {telegram_id} used invalid referrer ID (not found): {context.args[0]}")
            else: logger.warning(f"User {telegram_id} tried to refer themselves.")
        except (ValueError, IndexError): logger.warning(f"User {telegram_id} used invalid referral link format or no valid arg: {context.args}")

    db_user = await get_user(telegram_id); is_new_user = db_user is None
    today_date = datetime.date.today(); potential_todays_prize = await calculate_prize_for_date(today_date)
    welcome_message_parts = [f"Hello {first_name}! Welcome to TrustWin Bot!", "Get your tickets daily for a chance to win big in our USDT lottery!"]
    if is_new_user:
        created_user = await create_user(telegram_id, username, first_name, last_name, referrer_telegram_id)
        if created_user:
            welcome_message_parts.append("You've been registered! Thanks for joining.")
            if referrer_telegram_id:
                try:
                    new_user_display_name = first_name + (f" (@{username})" if username else "")
                    await context.bot.send_message(chat_id=referrer_telegram_id, text=f"Great news! Your referral {new_user_display_name} has joined TrustWin Bot using your link!\nYou'll earn {REFERRAL_PERCENT*100:.0f}% of the ticket price every time they buy a ticket!")
                    logger.info(f"Notified referrer {referrer_telegram_id} about new user {telegram_id}")
                except Exception as e: logger.warning(f"Could not notify referrer {referrer_telegram_id}: {e}")
        else: welcome_message_parts.append("There was an issue registering you. Please try /start again later.")
    welcome_message_parts.extend([f"\nToday's *potential* prize pool is currently around *{potential_todays_prize:.2f} USDT*.", "(This grows as more tickets are sold today for *tomorrow's* draw).", f"Each ticket costs *{TICKET_PRICE_USDT:.2f} USDT*.", "\nUse the /buy command to get your ticket(s)!", f"\nWant to earn passively? Share your unique referral link:", f"`https://t.me/{context.bot.username}?start={telegram_id}`", f"You get {REFERRAL_PERCENT*100:.0f}% of the ticket price for every ticket your referred friends buy, FOREVER!", "\nMay the odds be ever in your favor!"])
    welcome_message = "\n".join(welcome_message_parts)
    if update.message: await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
    else: logger.warning("Start command invoked without a message attribute in update.")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user;
    if not user: logger.warning("Buy command received without an effective_user."); return
    telegram_id = user.id
    db_user = await get_user(telegram_id);
    if not db_user:
        if update.message: await update.message.reply_text("Please use the /start command first to register."); return
    num_tickets_to_buy = 1; total_payment_due = num_tickets_to_buy * TICKET_PRICE_USDT
    callback_data_string = f"paid_{total_payment_due}_{num_tickets_to_buy}"
    keyboard = [[InlineKeyboardButton(f"I have paid {total_payment_due:.2f} USDT", callback_data=callback_data_string)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = (f"To buy {num_tickets_to_buy} ticket(s) for *{total_payment_due:.2f} USDT*:\n\n"
                    f"1. Send exactly *{total_payment_due:.2f} USDT (TRC-20)* to the following wallet address:\n"
                    f"`{USDT_WALLET}`\n\n"
                    "2. After sending, click the 'I have paid' button below.\n\n"
                    "Your ticket(s) will be counted for today's draw after admin verification. Good luck!")
    if update.message: await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def paid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query;
        # यह लाइन (और इसके नीचे की कुछ लाइनें) पुरानी लाइन 357 की जगह लेंगी
    if not query or not query.message:
        logger.error("paid_button_callback: invalid query or no message.")
        if query:  # यह सुनिश्चित करने के लिए कि query None नहीं है
            await query.answer("Error processing your request.", show_alert=True)
        return # फंक्शन से बाहर निकलें

    # इसके बाद आपका user = query.effective_user; वाला कोड शुरू होगा
    user = query.effective_user;
    if not user: logger.error("paid_button_callback: no effective_user."); await query.answer("Error: No user.", show_alert=True); return
    telegram_id = user.id; data = query.data
    await query.answer("Processing...")
    try:
        parts = data.split('_');
        if len(parts) != 3 or parts[0] != 'paid': raise ValueError("Callback format error")
        claimed_amount_paid = Decimal(parts[1]); num_tickets_claimed = int(parts[2])
        expected_amount_for_tickets = (num_tickets_claimed * TICKET_PRICE_USDT).quantize(Decimal("0.01"))
        if claimed_amount_paid.quantize(Decimal("0.01")) != expected_amount_for_tickets:
            error_msg = (f"Payment amount mismatch. Expected {expected_amount_for_tickets:.2f} for {num_tickets_claimed} ticket(s), claimed {claimed_amount_paid:.2f}. Contact admin or /buy again.")
            await query.edit_message_text(error_msg); logger.error(f"Payment mismatch user {telegram_id}: claimed {claimed_amount_paid}, expected {expected_amount_for_tickets} for {num_tickets_claimed} tickets."); return
    except (IndexError, ValueError, TypeError) as e:
        await query.edit_message_text("Invalid payment data. Try /buy again."); logger.error(f"Invalid callback data: '{data}' user {telegram_id}. Error: {e}"); return
    pending_payments[telegram_id] = {'amount_paid': claimed_amount_paid, 'num_tickets': num_tickets_claimed, 'date': datetime.date.today(), 'message_id': query.message.message_id, 'chat_id': query.message.chat_id}
    admin_notification_text = (f"Payment Claimed!\n\nUser: {user.first_name or 'N/A'} (@{user.username or 'N/A'}) [ID: `{telegram_id}`]\n"
                               f"Claimed for: *{num_tickets_claimed} ticket(s)* (Total {claimed_amount_paid:.2f} USDT)\nClaim Date: {datetime.date.today().isoformat()}\n\n"
                               f"Check payment and use `/confirm_payment {telegram_id}` if verified.")
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_notification_text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Admin {ADMIN_ID} notified: pending payment from {telegram_id} for {num_tickets_claimed} tickets.")
        await query.edit_message_text(f"Received your payment confirmation for {num_tickets_claimed} ticket(s) ({claimed_amount_paid:.2f} USDT).\nAdmin will verify. Tickets added shortly!")
    except Exception as e:
        logger.error(f"Failed to notify admin or edit user msg for {telegram_id}: {e}")
        try: await context.bot.send_message(chat_id=telegram_id, text=f"Received confirmation for {num_tickets_claimed} ticket(s).\nIssue notifying admin, but claim recorded. Wait for verification.")
        except Exception as e_user_notify: logger.error(f"Also failed to send direct notification to user {telegram_id}: {e_user_notify}")

# --- Admin Decorator ---
def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_to_check = update.effective_user
        if not user_to_check or user_to_check.id != ADMIN_ID:
            if update.message: await update.message.reply_text("You are not authorized.")
            elif update.callback_query: await update.callback_query.answer("Not authorized.", show_alert=True)
            logger.warning(f"Unauthorized access: user {user_to_check.id if user_to_check else 'Unknown'} for admin cmd.")
            return
        await handler(update, context)
    return wrapper

# --- Admin Commands ---
@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return
    total_users = await get_total_users_count(); todays_total_tickets_sold = await get_total_tickets_for_date(datetime.date.today())
    pending_count = len(pending_payments); potential_prize_for_tomorrows_draw = await calculate_prize_for_date(datetime.date.today())
    prize_for_todays_draw = await calculate_prize_for_date(datetime.date.today() - datetime.timedelta(days=1))
    stats_text = (f"Bot Statistics\n\nTotal Users: `{total_users}`\nToday's Tickets Sold (for tomorrow's draw): `{todays_total_tickets_sold}`\n"
                  f"Today's *Potential* Prize Pool (for tomorrow's draw): `{potential_prize_for_tomorrows_draw:.2f} USDT`\n"
                  f"Prize for *Today's* Draw (from yesterday's sales): `{prize_for_todays_draw:.2f} USDT`\n"
                  f"Pending Payments (Admin Verification): `{pending_count}`")
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return
    all_user_ids = await get_all_user_telegram_ids();
    if not all_user_ids: await update.message.reply_text("No users found."); return
    user_list_text = "Active Users\n\n"; display_limit = 50; limited_user_ids = all_user_ids[:display_limit]
    if len(all_user_ids) > display_limit: user_list_text += f"Listing first {display_limit} of {len(all_user_ids)} users:\n"
    if limited_user_ids:
        user_details_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', limited_user_ids).execute()
        user_details = user_details_response.data if user_details_response.data else []
        for user_data in user_details:
            name = user_data.get('first_name', 'N/A'); username_str = user_data.get('username'); user_id = user_data.get('telegram_id')
            user_list_text += f"- {name} (@{username_str or 'N/A'}) [ID: `{user_id}`]\n"
    else: user_list_text += "No users to list details for.\n"
    await update.message.reply_text(user_list_text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not context.args:
        if update.message: await update.message.reply_text("Usage: `/broadcast <message>`"); return
    message_text = " ".join(context.args); all_user_ids = await get_all_user_telegram_ids()
    if not all_user_ids:
        if update.message: await update.message.reply_text("No users to broadcast to."); return
    if update.message: await update.message.reply_text(f"Starting broadcast to {len(all_user_ids)} users...")
    await broadcast_message_to_users_list(context, all_user_ids, message_text)
    if update.message: await update.message.reply_text("Broadcast attempt finished. Check logs.")

@admin_only
async def confirm_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not context.args:
        if update.message: await update.message.reply_text("Usage: `/confirm_payment <user_id>`"); return
    try: user_to_confirm_id = int(context.args[0])
    except ValueError:
        if update.message: await update.message.reply_text("Invalid user ID."); return
    if user_to_confirm_id not in pending_payments:
        if update.message: await update.message.reply_text(f"No pending payment for user ID `{user_to_confirm_id}`."); return
    payment_info = pending_payments.pop(user_to_confirm_id)
    claimed_payment_amount_by_user = payment_info['amount_paid']; num_tickets_purchased = payment_info['num_tickets']
    original_message_id = payment_info['message_id']; original_chat_id = payment_info['chat_id']
    if not await increment_daily_tickets_for_user(user_to_confirm_id, num_tickets_purchased):
        logger.error(f"Failed to increment tickets for {user_to_confirm_id} (admin confirm).")
        pending_payments[user_to_confirm_id] = payment_info # Put back
        if update.message: await update.message.reply_text(f"Error incrementing tickets for {user_to_confirm_id}. Payment REVERTED. Check logs."); return
    referred_user_data = await get_user(user_to_confirm_id)
    if referred_user_data and referred_user_data.get('referrer_telegram_id'):
        referrer_id = referred_user_data['referrer_telegram_id']
        value_of_tickets_purchased = num_tickets_purchased * TICKET_PRICE_USDT
        referral_bonus = value_of_tickets_purchased * REFERRAL_PERCENT
        if referral_bonus > 0:
            await simulate_send_usdt(f"Referrer ID: {referrer_id}", referral_bonus, "Referral Bonus")
            try:
                referred_user_name = referred_user_data.get('first_name', f'User {user_to_confirm_id}')
                await context.bot.send_message(chat_id=referrer_id, text=f"Referral Bonus!\n\nYou earned *{referral_bonus:.2f} USDT* as {referred_user_name} bought {num_tickets_purchased} ticket(s)!", parse_mode=ParseMode.MARKDOWN)
                logger.info(f"Notified referrer {referrer_id} of {referral_bonus:.2f} USDT bonus from {user_to_confirm_id}")
            except Exception as e: logger.warning(f"Could not notify referrer {referrer_id} about bonus: {e}")
    try:
        user_tickets_res = supabase.from_('daily_tickets').select('count').eq('telegram_id', user_to_confirm_id).eq('date', datetime.date.today().isoformat()).single().execute()
        user_todays_total_tickets = user_tickets_res.data['count'] if user_tickets_res.data and isinstance(user_tickets_res.data.get('count'), int) else 0
        confirmation_text = (f"Your payment for {num_tickets_purchased} ticket(s) ({claimed_payment_amount_by_user:.2f} USDT) is confirmed!\n"
                             f"You now have *{user_todays_total_tickets}* ticket(s) for today's draw! Good luck!")
        try: await context.bot.edit_message_text(chat_id=original_chat_id, message_id=original_message_id, text=confirmation_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as edit_e:
             logger.warning(f"Failed to edit original payment msg for {user_to_confirm_id}: {edit_e}. Sending new.")
             await context.bot.send_message(chat_id=user_to_confirm_id, text=confirmation_text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Payment confirmed for user {user_to_confirm_id}. {num_tickets_purchased} tickets added.")
    except Exception as e: logger.error(f"Failed to notify user {user_to_confirm_id} about payment confirmation: {e}")
    if update.message: await update.message.reply_text(f"Payment confirmed for user ID `{user_to_confirm_id}`. {num_tickets_purchased} tickets added.")

@admin_only
async def manual_winner_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return
    await update.message.reply_text("Triggering manual winner draw for previous day...")
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    await perform_winner_draw(context, date_override=yesterday)
    await update.message.reply_text("Manual winner draw process complete. Check logs.")

# --- Scheduled Jobs ---
async def perform_winner_draw(context: ContextTypes.DEFAULT_TYPE, date_override: datetime.date | None = None) -> None:
    draw_date = date_override if date_override else datetime.date.today() - datetime.timedelta(days=1)
    logger.info(f"Starting winner draw for tickets of: {draw_date.isoformat()}")
    actual_prize_amount_for_draw = await calculate_prize_for_date(draw_date)
    logger.info(f"Calculated prize for {draw_date.isoformat()}: {actual_prize_amount_for_draw:.2f} USDT")
    if actual_prize_amount_for_draw <= Decimal("0.00"):
        logger.info(f"No prize pool for {draw_date.isoformat()}. No winner drawn.")
        broadcast_text = (f"Daily Draw Results for {draw_date.isoformat()}\n\nNo tickets sold, no prize pool this draw.\nBuy tickets today for tomorrow's chance!")
        user_ids_to_notify = await get_all_user_telegram_ids()
        if user_ids_to_notify: await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text)
        return
    ticket_entries_for_draw = await get_daily_ticket_entries_for_draw(draw_date)
    if not ticket_entries_for_draw:
        logger.warning(f"Prize > 0 for {draw_date.isoformat()}, but no ticket entries found. Inconsistency. No winner declared.")
        try: await context.bot.send_message(ADMIN_ID, f"WARNING: Inconsistency in draw for {draw_date.isoformat()}. Prize > 0 but no ticket entries. Investigate.")
        except Exception as e: logger.error(f"Failed to send inconsistency warning to admin: {e}")
        return
    weighted_ticket_list = []
    for entry in ticket_entries_for_draw:
        if entry.get('telegram_id') and isinstance(entry.get('count'), int) and entry['count'] > 0 :
            weighted_ticket_list.extend([entry['telegram_id']] * entry['count'])
    if not weighted_ticket_list:
        logger.info(f"Ticket entries found for {draw_date.isoformat()}, but weighted list is empty. No winner declared.")
        return
    winner_telegram_id = random.choice(weighted_ticket_list); winner_user_data = await get_user(winner_telegram_id)
    winner_name = winner_user_data.get('first_name', f'User {winner_telegram_id}') if winner_user_data else f'User {winner_telegram_id}'
    winner_username = winner_user_data.get('username', 'N/A') if winner_user_data else 'N/A'
    await simulate_send_usdt(f"Winner ID: {winner_telegram_id}", actual_prize_amount_for_draw, "Winner Prize")
    await add_winner_record(winner_telegram_id, actual_prize_amount_for_draw, draw_date)
    broadcast_text = (f"Daily Draw Results for {draw_date.isoformat()}\n\nWinner: *{winner_name}* (@{winner_username})!\n"
                      f"Congratulations! You won *{actual_prize_amount_for_draw:.2f} USDT*!\n\nBuy tickets today for the next draw!")
    user_ids_to_notify = await get_all_user_telegram_ids()
    if user_ids_to_notify: await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Winner {winner_telegram_id} drawn for {draw_date.isoformat()} with prize {actual_prize_amount_for_draw:.2f} USDT")

async def send_daily_marketing_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    message_content = await get_random_marketing_message_content()
    if not message_content: logger.warning("No marketing messages in DB."); return
    logger.info("Sending daily marketing message..."); user_ids = await get_all_user_telegram_ids()
    if not user_ids: logger.info("No users for marketing message."); return
    await broadcast_message_to_users_list(context, user_ids, message_content)

# --- Winners History Command ---
async def winners_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return
    latest_real_winners = await get_latest_winners(limit=7); winners_list_text = "TrustWin Bot Latest Winners\n\n"
    if not latest_real_winners: winners_list_text += "No winners yet! Be the first to win!\n"
    else:
        for i, winner_entry in enumerate(latest_real_winners):
            win_date_str = str(winner_entry.get('win_date', 'Unknown Date'))
            try: parsed_date = datetime.date.fromisoformat(win_date_str); win_date_display = parsed_date.strftime("%Y-%m-%d")
            except ValueError: win_date_display = win_date_str
            amount = Decimal(str(winner_entry.get('amount', '0'))).quantize(Decimal("0.01"))
            user_info = winner_entry.get('user_info')
            name = user_info.get('first_name', f"User {winner_entry.get('telegram_id')}") if user_info else f"User {winner_entry.get('telegram_id')}"
            winners_list_text += f"{i+1}. Date: {win_date_display}: *{name}* won *{amount:.2f} USDT*\n"
    await update.message.reply_text(winners_list_text, parse_mode=ParseMode.MARKDOWN)

# --- Error Handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    try:
        error_summary = str(context.error)[:1000]; update_str = str(update) if isinstance(update, Update) else str(type(update)); update_summary = update_str[:1000]
        error_message = f"Bot Error Alert!\n\nError Type: {type(context.error).__name__}\nError: {error_summary}\n\nUpdate Type: {type(update).__name__}\nUpdate Details: {update_summary}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_message)
    except Exception as e_notify: logger.error(f"CRITICAL: Failed to send error notification to admin {ADMIN_ID}. Original error: {context.error}. Notification error: {e_notify}")

# --- Main Function ---
def main() -> None:
    logger.info("Attempting to start TrustWin Bot...")
    try: application = Application.builder().token(BOT_TOKEN).build(); logger.info("Telegram Application built.")
    except Exception as e: logger.critical(f"FATAL: Failed to build Telegram App: {e}. Bot cannot start."); return
    job_queue = application.job_queue
    if not job_queue: logger.critical("FATAL: No job queue. Scheduled tasks cannot run. Bot cannot start reliably."); return
    try: timezone = pytz.timezone(TIMEZONE_STR); logger.info(f"Scheduler timezone: {TIMEZONE_STR}")
    except pytz.exceptions.UnknownTimeZoneError: logger.error(f"Unknown timezone: '{TIMEZONE_STR}'. Defaulting to UTC."); timezone = pytz.utc
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("winners", winners_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("confirm_payment", confirm_payment_command))
    application.add_handler(CommandHandler("trigger_draw", manual_winner_draw_command))
    application.add_handler(CallbackQueryHandler(paid_button_callback, pattern='^paid_'))
    application.add_error_handler(error_handler)
    job_queue.run_daily(perform_winner_draw, time=datetime.time(hour=0, minute=1, second=0, tzinfo=timezone), name="daily_winner_draw")
    logger.info(f"Scheduled daily winner draw at 00:01 ({timezone}) for previous day's tickets.")
    job_queue.run_daily(send_daily_marketing_message_job, time=datetime.time(hour=9, minute=0, second=0, tzinfo=timezone), name="daily_marketing_message")
    logger.info(f"Scheduled daily marketing message at 09:00 ({timezone}).")
    logger.info("Bot is starting to poll for updates...")
    try: application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e: logger.critical(f"Bot polling failed critically: {e}. Bot has stopped.")
    logger.info("Bot polling has ended.")

if __name__ == '__main__':
    main()
