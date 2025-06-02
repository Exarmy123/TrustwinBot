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

from supabase.client import create_client, Client # Sahi import

import pytz

# --- Logging Configuration (इसे एनवायरनमेंट वेरिएबल लोड होने के ठीक बाद रखें) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG # DEBUG पर सेट किया गया
)
logger = logging.getLogger(__name__) # logger को यहाँ डिफाइन करें
logger.info("STAGE 0: Script started, basic logging configured.")

# --- Environment Variables ---
# load_dotenv() # Uncomment if using a .env file
logger.info("STAGE 1: Attempting to load environment variables.")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
USDT_WALLET = os.getenv("USDT_WALLET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

TICKET_PRICE_USDT_STR = os.getenv("TICKET_PRICE_USDT", "4.0")
REFERRAL_PERCENT_STR = os.getenv("REFERRAL_PERCENT", "0.25")
GLOBAL_CRYPTO_TAX_PERCENT_STR = os.getenv("GLOBAL_CRYPTO_TAX_PERCENT", "0.25")
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Kolkata")

logger.debug(f"STAGE 2.0: BOT_TOKEN loaded: {bool(BOT_TOKEN)}")
logger.debug(f"STAGE 2.1: ADMIN_ID_STR loaded: {bool(ADMIN_ID_STR)}")
logger.debug(f"STAGE 2.2: USDT_WALLET loaded: {bool(USDT_WALLET)}")
# STAGE 2.3 aur 2.4 ke log neeche Supabase client initialization ke paas move kar diye hain specific value ke saath
logger.debug(f"STAGE 2.5: TICKET_PRICE_USDT_STR loaded: {bool(TICKET_PRICE_USDT_STR)} (Value: {TICKET_PRICE_USDT_STR})")
logger.debug(f"STAGE 2.6: REFERRAL_PERCENT_STR loaded: {bool(REFERRAL_PERCENT_STR)} (Value: {REFERRAL_PERCENT_STR})")
logger.debug(f"STAGE 2.7: GLOBAL_CRYPTO_TAX_PERCENT_STR loaded: {bool(GLOBAL_CRYPTO_TAX_PERCENT_STR)} (Value: {GLOBAL_CRYPTO_TAX_PERCENT_STR})")
logger.debug(f"STAGE 2.8: TIMEZONE_STR loaded: {bool(TIMEZONE_STR)} (Value: {TIMEZONE_STR})")

# Validate and convert environment variables
if not all([BOT_TOKEN, ADMIN_ID_STR, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY]):
    logger.error("FATAL: Missing required core environment variables! Exiting.")
    if not BOT_TOKEN: logger.error("DEBUG CHECK: BOT_TOKEN specifically is missing or empty.")
    if not ADMIN_ID_STR: logger.error("DEBUG CHECK: ADMIN_ID_STR (for ADMIN_ID key) specifically is missing or empty.")
    if not USDT_WALLET: logger.error("DEBUG CHECK: USDT_WALLET specifically is missing or empty.")
    if not SUPABASE_URL: logger.error("DEBUG CHECK: SUPABASE_URL specifically is missing or empty.")
    if not SUPABASE_KEY: logger.error("DEBUG CHECK: SUPABASE_KEY specifically is missing or empty.")
    exit(1)
logger.info("STAGE 3: Core environment variables validated.")

try:
    ADMIN_ID = int(ADMIN_ID_STR)
    TICKET_PRICE_USDT = Decimal(TICKET_PRICE_USDT_STR)
    REFERRAL_PERCENT = Decimal(REFERRAL_PERCENT_STR)
    GLOBAL_CRYPTO_TAX_PERCENT = Decimal(GLOBAL_CRYPTO_TAX_PERCENT_STR)
    logger.info("STAGE 4.0: Basic numeric environment variables converted.")

    if not (Decimal(0) <= REFERRAL_PERCENT <= Decimal(1)):
        logger.error("FATAL: REFERRAL_PERCENT must be between 0 and 1. Exiting.")
        exit(1)
    if not (Decimal(0) <= GLOBAL_CRYPTO_TAX_PERCENT <= Decimal(1)):
        logger.error("FATAL: GLOBAL_CRYPTO_TAX_PERCENT must be between 0 and 1. Exiting.")
        exit(1)
    if (REFERRAL_PERCENT + GLOBAL_CRYPTO_TAX_PERCENT) > Decimal(1):
        logger.error("FATAL: Sum of REFERRAL_PERCENT and GLOBAL_CRYPTO_TAX_PERCENT cannot exceed 1. Exiting.")
        exit(1)
    logger.info("STAGE 4.1: Percentage variables validated.")

except ValueError as e:
    logger.error(f"FATAL: Invalid format for numeric environment variables: {e}. Exiting.")
    exit(1)

# Calculate Prize Pool Contribution Percentage
PRIZE_POOL_CONTRIBUTION_PERCENT = Decimal(1) - REFERRAL_PERCENT - GLOBAL_CRYPTO_TAX_PERCENT
if PRIZE_POOL_CONTRIBUTION_PERCENT < Decimal(0):
    logger.error("FATAL: Prize pool contribution percentage is negative. Check referral and tax percentages. Exiting.")
    exit(1)
logger.info("STAGE 5: Prize pool contribution calculated.")

logger.info(f"Ticket Price: {TICKET_PRICE_USDT} USDT")
logger.info(f"Referral Percent: {REFERRAL_PERCENT*100}%")
logger.info(f"Global Crypto Tax Percent: {GLOBAL_CRYPTO_TAX_PERCENT*100}%")
logger.info(f"Prize Pool Contribution Percent: {PRIZE_POOL_CONTRIBUTION_PERCENT*100}%")

# --- Supabase Client ---
logger.info("STAGE 6: Attempting to connect to Supabase.")

# Logging the actual values being used for Supabase connection
# Note: SUPABASE_KEY poora log karna sensitive ho sakta hai production mein,
# par debugging ke liye key ka loaded hona check karna zaroori hai.
# Agar SUPABASE_URL ya SUPABASE_KEY None hai, toh yeh yahan pata chal jayega.
logger.debug(f"DEBUG STAGE 6 - SUPABASE_URL from env: '{SUPABASE_URL}' (Type: {type(SUPABASE_URL)})")
if SUPABASE_KEY and len(SUPABASE_KEY) > 10:
    logger.debug(f"DEBUG STAGE 6 - SUPABASE_KEY from env: '{SUPABASE_KEY[:5]}...{SUPABASE_KEY[-5:]}' (Loaded: True, Type: {type(SUPABASE_KEY)})")
elif SUPABASE_KEY:
    logger.debug(f"DEBUG STAGE 6 - SUPABASE_KEY from env: 'Key is short or unusual length' (Loaded: True, Type: {type(SUPABASE_KEY)})")
else:
    logger.debug("DEBUG STAGE 6 - SUPABASE_KEY from env: Not loaded or empty (Loaded: False)")

try:
    if not SUPABASE_URL or not SUPABASE_KEY:
        # Yeh check yahan bhi daal diya hai, just in case upar wala all() miss kar gaya
        # ya environment variables baad mein None ho gaye (jo ki aam taur par nahi hota)
        logger.error("FATAL: SUPABASE_URL or SUPABASE_KEY is None before client creation. Exiting.")
        exit(1)
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("STAGE 6.1: Successfully initialized Supabase client.")
except Exception as e:
    logger.error(f"FATAL: Could not initialize Supabase client: {e}. Exiting.")
    # Additional logging for URL specific errors
    if "Invalid URL" in str(e) and SUPABASE_URL:
        logger.error(f"Details for Invalid URL: URL received by client was '{SUPABASE_URL}'")
    elif "Invalid URL" in str(e) and not SUPABASE_URL:
        logger.error("Details for Invalid URL: SUPABASE_URL was None or empty when client tried to use it.")
    exit(1)

# --- Global State (for pending payments - Simple in-memory approach) ---
pending_payments = {} # {user_id: {amount_paid: Decimal, num_tickets: int, message_id: int, date: date, chat_id: int}}
logger.debug("STAGE 7: Global state 'pending_payments' initialized.")

# --- Helper Functions: Database ---
async def get_user(telegram_id: int):
    """Fetch a user from the database by telegram_id."""
    logger.debug(f"DB: Attempting to get user {telegram_id}")
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).single().execute()
        logger.debug(f"DB: Get user {telegram_id} response: {response.data is not None}")
        return response.data
    except Exception as e:
        # Supabase-py v1 vs v2 error checking for "0 rows" on .single()
        if hasattr(e, 'message') and "PGRST116" in e.message and "0 rows" in e.message: # older supabase-py
            logger.debug(f"Supabase: User {telegram_id} not found (0 rows for single() - old lib).")
        elif hasattr(e, 'code') and e.code == 'PGRST116': # supabase-py v1.x
            logger.debug(f"Supabase: User {telegram_id} not found (PGRST116 for single() - v1.x).")
        elif hasattr(e, 'details') and isinstance(e.details, str) and 'PGRST116' in e.details: # supabase-py v2.x
             logger.debug(f"Supabase: User {telegram_id} not found (PGRST116 from details for single() - v2.x).")
        else:
            logger.error(f"Supabase error fetching user {telegram_id}: {type(e)} - {e}")
        return None

async def create_user(telegram_id: int, username: str | None, first_name: str | None, last_name: str | None, referrer_telegram_id: int | None = None):
    """Create a new user in the database."""
    logger.debug(f"DB: Attempting to create user {telegram_id}")
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
        
        error_msg = "Unknown error creating user."
        if hasattr(response, 'error') and response.error:
            error_msg = response.error.message
            if hasattr(response.error, 'details') and response.error.details: 
                error_msg += f" Details: {response.error.details}"
            elif hasattr(response.error, 'hint') and response.error.hint:
                error_msg += f" Hint: {response.error.hint}"
        logger.error(f"Supabase error creating user {telegram_id}: {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Exception creating user {telegram_id}: {e}")
        return None

async def increment_daily_tickets_for_user(telegram_id: int, num_tickets: int = 1):
    """Increment ticket count for a user for today's date using RPC."""
    logger.debug(f"DB: Attempting to increment {num_tickets} tickets for user {telegram_id} via RPC.")
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
        
        logger.info(f"{num_tickets} tickets incremented via RPC for user {telegram_id} for {today_iso}.")
        return True
    except Exception as e: 
        logger.error(f"Exception calling RPC increment_daily_ticket for user {telegram_id} ({num_tickets} tickets): {e}")
        if hasattr(e, 'message'): logger.error(f"RPC Exception details: {getattr(e, 'message', 'N/A')}")
        if hasattr(e, 'details'): logger.error(f"RPC Exception details: {getattr(e, 'details', 'N/A')}")
        if hasattr(e, 'hint'): logger.error(f"RPC Exception hint: {getattr(e, 'hint', 'N/A')}")
        return False


async def get_total_tickets_for_date(date_obj: datetime.date) -> int:
    """Get the total number of tickets sold on a specific date."""
    logger.debug(f"DB: Getting total tickets for date {date_obj.isoformat()}")
    try:
        response = supabase.from_('daily_tickets').select('count').eq('date', date_obj.isoformat()).execute()
        
        if response.data:
            total = sum(item['count'] for item in response.data if isinstance(item.get('count'), int))
            logger.debug(f"DB: Total tickets for {date_obj.isoformat()}: {total}")
            return total
        logger.debug(f"DB: No ticket data found for {date_obj.isoformat()} to sum.")
        return 0
    except Exception as e:
        logger.error(f"Supabase error fetching total tickets for {date_obj}: {e}")
        return 0

async def get_daily_ticket_entries_for_draw(date_obj: datetime.date) -> list:
    """Get all individual ticket entries (telegram_id, count) for a specific date."""
    logger.debug(f"DB: Getting daily ticket entries for draw on {date_obj.isoformat()}")
    try:
        response = supabase.from_('daily_tickets').select('telegram_id, count').eq('date', date_obj.isoformat()).execute()
        logger.debug(f"DB: Fetched {len(response.data) if response.data else 0} entries for draw on {date_obj.isoformat()}")
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Supabase error fetching daily ticket entries for {date_obj} for draw: {e}")
        return []

async def add_winner_record(telegram_id: int, amount: Decimal, win_date: datetime.date):
    """Add a winner entry to the database."""
    logger.debug(f"DB: Adding winner record for {telegram_id}, amount {amount}, date {win_date.isoformat()}")
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
        error_msg = response.error.message if hasattr(response, 'error') and response.error else "Unknown error adding winner"
        logger.error(f"Supabase error adding winner {telegram_id}: {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Exception adding winner {telegram_id}: {e}")
        return None

async def get_latest_winners(limit: int = 7):
    """Fetch the latest winners from the database, including user info."""
    logger.debug(f"DB: Getting latest {limit} winners.")
    try:
        winners_response = supabase.from_('winners').select('telegram_id, amount, win_date').order('win_date', desc=True).limit(limit).execute()
        if not winners_response.data:
            logger.debug("DB: No winners found.")
            return []
        
        logger.debug(f"DB: Found {len(winners_response.data)} raw winner entries.")
        winner_telegram_ids = [w['telegram_id'] for w in winners_response.data]

        if not winner_telegram_ids:
             return winners_response.data 

        users_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', winner_telegram_ids).execute()
        user_map = {user['telegram_id']: user for user in users_response.data} if users_response.data else {}
        logger.debug(f"DB: Fetched user info for {len(user_map)} winners.")

        for winner in winners_response.data:
            winner['user_info'] = user_map.get(winner['telegram_id'])
        
        return winners_response.data
    except Exception as e:
        logger.error(f"Supabase error fetching latest winners: {e}")
        return []

async def get_all_user_telegram_ids() -> list[int]:
    """Fetch all user telegram_ids for broadcasting."""
    logger.debug("DB: Getting all user telegram_ids.")
    try:
        response = supabase.from_('users').select('telegram_id').execute()
        ids = [user['telegram_id'] for user in response.data] if response.data else []
        logger.debug(f"DB: Found {len(ids)} user telegram_ids.")
        return ids
    except Exception as e:
        logger.error(f"Supabase error fetching all user telegram_ids: {e}")
        return []

async def get_total_users_count() -> int:
    """Get the total count of users."""
    logger.debug("DB: Getting total users count.")
    try:
        response = supabase.from_('users').select('telegram_id', count='exact').limit(0).execute()
        count = response.count if response.count is not None else 0
        logger.debug(f"DB: Total users count: {count}")
        return count
    except Exception as e:
        logger.error(f"Supabase error fetching total users count: {e}")
        return 0

async def get_random_marketing_message_content() -> str | None:
    """Fetch a random marketing message from the database."""
    logger.debug("DB: Getting random marketing message.")
    try:
        response = supabase.from_('messages').select('content').eq('type', 'marketing').execute()
        if response.data:
            messages = [msg['content'] for msg in response.data if msg.get('content')]
            if messages:
                selected_message = random.choice(messages)
                logger.debug("DB: Random marketing message selected.")
                return selected_message
            else:
                logger.debug("DB: No marketing messages with content found.")
                return None
        logger.debug("DB: No marketing messages found in table.")
        return None
    except Exception as e:
        logger.error(f"Supabase error fetching marketing message: {e}")
        return None

# --- Helper: Calculate Dynamic Prize ---
async def calculate_prize_for_date(date_obj: datetime.date) -> Decimal:
    """Calculates the winner prize for a given date based on ticket sales."""
    logger.debug(f"CALC: Calculating prize for date {date_obj.isoformat()}")
    total_tickets_sold_on_date = await get_total_tickets_for_date(date_obj)
    logger.info(f"Total tickets sold on {date_obj.isoformat()} for prize calculation: {total_tickets_sold_on_date}")
    if total_tickets_sold_on_date == 0:
        logger.debug(f"CALC: No tickets sold on {date_obj.isoformat()}, prize is 0.")
        return Decimal("0.00")
    total_revenue_from_tickets = total_tickets_sold_on_date * TICKET_PRICE_USDT
    prize_amount = total_revenue_from_tickets * PRIZE_POOL_CONTRIBUTION_PERCENT
    final_prize = prize_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    logger.debug(f"CALC: Prize for {date_obj.isoformat()} calculated: {final_prize} USDT")
    return final_prize

# --- Helper Functions: USDT Simulation & Broadcast ---
async def simulate_send_usdt(recipient_info: str, amount: Decimal, transaction_type: str):
    logger.info(f"SIMULATING USDT SEND: Type='{transaction_type}', Recipient='{recipient_info}', Amount='{amount:.2f} USDT'")
    await asyncio.sleep(random.uniform(0.5, 1.2)) 
    logger.info(f"SIMULATION COMPLETE: USDT sent successfully (simulated).")
    return True 

async def broadcast_message_to_users_list(context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str, parse_mode: str | None = None):
    sent_count = 0
    failed_count = 0
    tasks = []
    logger.debug(f"BROADCAST: Preparing to send to {len(user_ids)} users.")

    async def send_single_message(user_id_to_send: int):
        nonlocal sent_count, failed_count 
        try:
            await context.bot.send_message(chat_id=user_id_to_send, text=text, parse_mode=parse_mode)
            sent_count += 1
            logger.debug(f"BROADCAST: Message sent to {user_id_to_send}")
        except Exception as e:
            logger.warning(f"BROADCAST: Failed to send message to user {user_id_to_send}: {e}")
            failed_count +=1
            
    for user_id in user_ids:
        tasks.append(send_single_message(user_id))
    
    if tasks:
        await asyncio.gather(*tasks)
    
    logger.info(f"BROADCAST: Attempt finished. Sent: {sent_count}, Failed: {failed_count} out of {len(user_ids)} users.")

# --- Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER: start_command invoked.")
    user = update.effective_user
    if not user:
        logger.warning("Start command received without an effective_user. Skipping.")
        return

    telegram_id = user.id
    username = user.username
    first_name = user.first_name or "User" 
    last_name = user.last_name
    logger.info(f"Start command from user: {telegram_id} ({first_name} @{username})")

    referrer_telegram_id = None
    if context.args:
        logger.debug(f"Start command args: {context.args}")
        try:
            potential_referrer_id = int(context.args[0])
            if potential_referrer_id != telegram_id:
                referrer_user = await get_user(potential_referrer_id)
                if referrer_user:
                    referrer_telegram_id = potential_referrer_id
                    logger.info(f"User {telegram_id} started with referrer {referrer_telegram_id}")
                else:
                    logger.warning(f"User {telegram_id} used invalid referrer ID (not found): {context.args[0]}")
            else:
                logger.warning(f"User {telegram_id} tried to refer themselves.")
        except (ValueError, IndexError):
            logger.warning(f"User {telegram_id} used invalid referral link format or no valid arg: {context.args}")

    db_user = await get_user(telegram_id)
    is_new_user = db_user is None
    logger.debug(f"User {telegram_id} is_new_user: {is_new_user}")

    today_date = datetime.date.today()
    potential_todays_prize = await calculate_prize_for_date(today_date)
    logger.debug(f"Potential today's prize for welcome message: {potential_todays_prize:.2f} USDT")

    welcome_message_parts = [
        f"Hello {first_name}! Welcome to TrustWin Bot!",
        "Get your tickets daily for a chance to win big in our USDT lottery!"
    ]

    if is_new_user:
        logger.info(f"User {telegram_id} is new. Creating entry...")
        created_user = await create_user(telegram_id, username, first_name, last_name, referrer_telegram_id)
        if created_user:
            welcome_message_parts.append("You've been registered! Thanks for joining.")
            logger.info(f"User {telegram_id} successfully registered.")
            if referrer_telegram_id:
                try:
                    new_user_display_name = first_name + (f" (@{username})" if username else "")
                    referral_notification_text = (
                        f"Great news! Your referral {new_user_display_name} has joined TrustWin Bot using your link!\n"
                        f"You'll earn {REFERRAL_PERCENT*100:.0f}% of the ticket price every time they buy a ticket!"
                    )
                    await context.bot.send_message(chat_id=referrer_telegram_id, text=referral_notification_text)
                    logger.info(f"Notified referrer {referrer_telegram_id} about new user {telegram_id}")
                except Exception as e:
                    logger.warning(f"Could not notify referrer {referrer_telegram_id}: {e}")
        else:
            welcome_message_parts.append("There was an issue registering you. Please try /start again later.")
            logger.error(f"Failed to register new user {telegram_id}.")
    
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
        logger.debug(f"Welcome message sent to {telegram_id}")
    else:
        logger.warning("Start command invoked without a message attribute in update. Cannot send reply.")


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER: buy_command invoked.")
    user = update.effective_user
    if not user:
        logger.warning("Buy command received without an effective_user. Skipping.")
        return
    
    telegram_id = user.id
    logger.info(f"Buy command from user: {telegram_id}")

    db_user = await get_user(telegram_id)
    if not db_user:
        if update.message:
            await update.message.reply_text("Please use the /start command first to register.")
            logger.info(f"User {telegram_id} tried /buy without being registered.")
        return

    num_tickets_to_buy = 1 
    total_payment_due = num_tickets_to_buy * TICKET_PRICE_USDT
    callback_data_string = f"paid_{total_payment_due}_{num_tickets_to_buy}"
    logger.debug(f"Buy command: {num_tickets_to_buy} ticket(s), total due {total_payment_due:.2f} USDT, callback_data: {callback_data_string}")

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
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        logger.debug(f"Buy instruction message sent to {telegram_id}")
    else:
        logger.warning("Buy command invoked without message attribute. Cannot send reply.")


async def paid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER: paid_button_callback invoked.")
    query = update.callback_query

    if not query or not query.message:
        logger.error("paid_button_callback: invalid query or no message.")
        if query:  
            try:
                await query.answer("Error processing your request.", show_alert=True)
            except Exception as e_ans:
                 logger.error(f"Error sending answer in paid_button_callback for invalid query: {e_ans}")
        return

    user = query.effective_user
    if not user:
        logger.error("paid_button_callback: no effective_user.")
        await query.answer("Error: No user identified.", show_alert=True)
        return
    
    telegram_id = user.id
    data = query.data
    logger.info(f"Paid button callback from user {telegram_id} with data: {data}")
    
    await query.answer("Processing...") 
    logger.debug(f"Initial 'Processing...' answer sent to callback query from {telegram_id}")

    try:
        parts = data.split('_')
        if len(parts) != 3 or parts[0] != 'paid':
            logger.error(f"Invalid callback data format: '{data}' for user {telegram_id}")
            raise ValueError("Callback format error")
        
        claimed_amount_paid_str = parts[1]
        num_tickets_claimed_str = parts[2]
        
        claimed_amount_paid = Decimal(claimed_amount_paid_str)
        num_tickets_claimed = int(num_tickets_claimed_str)
        logger.debug(f"User {telegram_id} claims paid {claimed_amount_paid} for {num_tickets_claimed} tickets.")

        expected_amount_for_tickets = (num_tickets_claimed * TICKET_PRICE_USDT).quantize(Decimal("0.01"))

        if claimed_amount_paid.quantize(Decimal("0.01")) != expected_amount_for_tickets:
            error_msg = (
                f"Payment amount mismatch. Expected {expected_amount_for_tickets:.2f} for {num_tickets_claimed} ticket(s), "
                f"claimed {claimed_amount_paid:.2f}. Please contact admin or use /buy again with the correct amount."
            )
            await query.edit_message_text(error_msg)
            logger.error(f"Payment mismatch for user {telegram_id}: claimed {claimed_amount_paid}, expected {expected_amount_for_tickets} for {num_tickets_claimed} tickets.")
            return
        
    except (IndexError, ValueError, TypeError) as e:
        await query.edit_message_text("There was an issue with your payment claim data. Please try the /buy command again.")
        logger.error(f"Invalid callback data processing for user {telegram_id}: data='{data}', Error: {e}")
        return

    pending_payments[telegram_id] = {
        'amount_paid': claimed_amount_paid,
        'num_tickets': num_tickets_claimed,
        'date': datetime.date.today(), 
        'message_id': query.message.message_id,
        'chat_id': query.message.chat_id
    }
    logger.info(f"Pending payment for user {telegram_id} recorded: {num_tickets_claimed} tickets, {claimed_amount_paid:.2f} USDT.")

    admin_notification_text = (
        f"🔔 Payment Claimed! 🔔\n\n"
        f"User: {user.first_name or 'N/A'} (@{user.username or 'N/A'}) [ID: `{telegram_id}`]\n"
        f"Claimed for: *{num_tickets_claimed} ticket(s)* (Total {claimed_amount_paid:.2f} USDT)\n"
        f"Claim Date: {datetime.date.today().isoformat()}\n\n"
        f"➡️ Please verify payment and use `/confirm_payment {telegram_id}` if correct."
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_notification_text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Admin {ADMIN_ID} notified about pending payment from {telegram_id}.")
        
        await query.edit_message_text(
            f"✅ Received your payment confirmation for {num_tickets_claimed} ticket(s) ({claimed_amount_paid:.2f} USDT).\n"
            f"The admin will verify your payment shortly. Once confirmed, your tickets will be added for today's draw!"
        )
        logger.debug(f"User {telegram_id} notified about pending verification.")

    except Exception as e:
        logger.error(f"Failed to notify admin or edit user message for {telegram_id}'s payment claim: {e}")
        try:
            await context.bot.send_message(
                chat_id=telegram_id, 
                text=(f"Received your payment confirmation for {num_tickets_claimed} ticket(s).\n"
                      f"There was an issue updating the original message, but your claim is recorded.\n"
                      f"Admin will verify. Thank you!")
            )
        except Exception as e_user_notify_fallback:
            logger.error(f"Also failed to send direct fallback notification to user {telegram_id}: {e_user_notify_fallback}")

# --- Admin Decorator ---
def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.debug(f"ADMIN_DECORATOR: Checking access for handler {handler.__name__}")
        user_to_check = update.effective_user
        if not user_to_check or user_to_check.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("You are not authorized to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("You are not authorized for this action.", show_alert=True)
            logger.warning(f"Unauthorized access attempt: user {user_to_check.id if user_to_check else 'Unknown'} for admin command {handler.__name__}.")
            return
        logger.debug(f"ADMIN_DECORATOR: Access granted for user {user_to_check.id} to {handler.__name__}")
        await handler(update, context)
    return wrapper

# --- Admin Commands ---
@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER_ADMIN: stats_command invoked.")
    if not update.message: return 

    total_users = await get_total_users_count()
    todays_total_tickets_sold = await get_total_tickets_for_date(datetime.date.today())
    pending_count = len(pending_payments)
    potential_prize_for_tomorrows_draw = await calculate_prize_for_date(datetime.date.today()) 
    prize_for_todays_draw = await calculate_prize_for_date(datetime.date.today() - datetime.timedelta(days=1)) 

    stats_text = (
        f"📊 **TrustWin Bot Statistics** 📊\n\n"
        f"👤 Total Users: `{total_users}`\n"
        f"🎟️ Today's Tickets Sold (for tomorrow's draw): `{todays_total_tickets_sold}`\n"
        f"💰 Today's *Potential* Prize Pool (for tomorrow's draw): `{potential_prize_for_tomorrows_draw:.2f} USDT`\n"
        f"🏆 Prize for *Today's* Draw (from yesterday's sales): `{prize_for_todays_draw:.2f} USDT`\n"
        f"⏳ Pending Payments (Admin Verification): `{pending_count}`"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    logger.info("Admin stats displayed.")

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER_ADMIN: users_command invoked.")
    if not update.message: return

    all_user_ids = await get_all_user_telegram_ids()
    if not all_user_ids:
        await update.message.reply_text("No users found in the database.")
        return

    user_list_text = "👥 **Active Users List** 👥\n\n"
    display_limit = 50 
    limited_user_ids = all_user_ids[:display_limit]

    if len(all_user_ids) > display_limit:
        user_list_text += f"Displaying first {display_limit} of {len(all_user_ids)} total users:\n"
    
    if limited_user_ids:
        users_details_response = supabase.from_('users').select('telegram_id, username, first_name').in_('telegram_id', limited_user_ids).execute()
        
        if users_details_response.data:
            for i, user_data in enumerate(users_details_response.data):
                name = user_data.get('first_name', 'N/A')
                username_str = user_data.get('username')
                user_id = user_data.get('telegram_id')
                user_list_text += f"{i+1}. {name} (@{username_str or 'N/A'}) [ID: `{user_id}`]\n"
        else:
            user_list_text += "Could not fetch user details for the listed IDs.\n"
    else:
        user_list_text += "No users to list details for.\n"
        
    await update.message.reply_text(user_list_text, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Admin users list displayed (limit {display_limit}).")


@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER_ADMIN: broadcast_command invoked.")
    if not update.message or not context.args:
        if update.message:
            await update.message.reply_text("Usage: `/broadcast <your message text here>`")
        return

    message_text = " ".join(context.args)
    all_user_ids = await get_all_user_telegram_ids()

    if not all_user_ids:
        if update.message:
            await update.message.reply_text("No users found to broadcast the message to.")
        return

    if update.message:
        await update.message.reply_text(f"📢 Starting broadcast of your message to {len(all_user_ids)} users...")
    
    await broadcast_message_to_users_list(context, all_user_ids, message_text, parse_mode=ParseMode.MARKDOWN) 
    
    if update.message:
        await update.message.reply_text("Broadcast attempt finished. Please check the bot logs for details on sent/failed messages.")
    logger.info(f"Admin initiated broadcast to {len(all_user_ids)} users.")


@admin_only
async def confirm_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER_ADMIN: confirm_payment_command invoked.")
    if not update.message or not context.args:
        if update.message:
            await update.message.reply_text("Usage: `/confirm_payment <user_id>`")
        return

    try:
        user_to_confirm_id = int(context.args[0])
    except ValueError:
        if update.message:
            await update.message.reply_text("Invalid User ID format. Please provide a numeric User ID.")
        return
    
    logger.info(f"Admin attempts to confirm payment for user ID: {user_to_confirm_id}")

    if user_to_confirm_id not in pending_payments:
        if update.message:
            await update.message.reply_text(f"No pending payment found for User ID `{user_to_confirm_id}`. It might have already been processed or was never claimed.")
        logger.warning(f"No pending payment for user {user_to_confirm_id} found by admin.")
        return

    payment_info = pending_payments.pop(user_to_confirm_id) 
    claimed_payment_amount_by_user = payment_info['amount_paid']
    num_tickets_purchased = payment_info['num_tickets']
    original_message_id = payment_info['message_id']
    original_chat_id = payment_info['chat_id'] 

    logger.info(f"Processing payment confirmation for user {user_to_confirm_id}: {num_tickets_purchased} tickets, {claimed_payment_amount_by_user:.2f} USDT.")

    if not await increment_daily_tickets_for_user(user_to_confirm_id, num_tickets_purchased):
        logger.error(f"Failed to increment tickets in DB for {user_to_confirm_id} after admin confirmation. Reverting pending payment.")
        pending_payments[user_to_confirm_id] = payment_info 
        if update.message:
            await update.message.reply_text(f"❌ Error: Could not increment tickets for User ID `{user_to_confirm_id}` in the database. The payment claim has been reverted to pending. Please check logs and try again.")
        return

    referred_user_data = await get_user(user_to_confirm_id)
    if referred_user_data and referred_user_data.get('referrer_telegram_id'):
        referrer_id = referred_user_data['referrer_telegram_id']
        value_of_tickets_purchased = num_tickets_purchased * TICKET_PRICE_USDT 
        referral_bonus = value_of_tickets_purchased * REFERRAL_PERCENT
        
        if referral_bonus > 0:
            logger.info(f"Referral bonus of {referral_bonus:.2f} USDT due to referrer {referrer_id} for user {user_to_confirm_id}'s purchase.")
            await simulate_send_usdt(f"Referrer ID: {referrer_id}", referral_bonus, "Referral Bonus")
            try:
                referred_user_name = referred_user_data.get('first_name', f'User {user_to_confirm_id}')
                await context.bot.send_message(
                    chat_id=referrer_id, 
                    text=(f"🎉 Referral Bonus! 🎉\n\n"
                          f"You earned *{referral_bonus:.2f} USDT* because your referral, {referred_user_name}, "
                          f"bought {num_tickets_purchased} ticket(s)!"),
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Notified referrer {referrer_id} of {referral_bonus:.2f} USDT bonus from {user_to_confirm_id}'s purchase.")
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_id} about their bonus: {e}")

    try:
        user_tickets_res = supabase.from_('daily_tickets').select('count').eq('telegram_id', user_to_confirm_id).eq('date', datetime.date.today().isoformat()).single().execute()
        user_todays_total_tickets = 0
        if user_tickets_res.data and isinstance(user_tickets_res.data.get('count'), int) :
             user_todays_total_tickets = user_tickets_res.data['count']
        else:
             logger.warning(f"Could not retrieve total daily tickets for user {user_to_confirm_id} after confirmation. Response: {user_tickets_res.data}. Assuming newly purchased are the total for message.")
             user_todays_total_tickets = num_tickets_purchased 
        confirmation_text_to_user = (
            f"✅ Your payment for {num_tickets_purchased} ticket(s) ({claimed_payment_amount_by_user:.2f} USDT) is confirmed!\n"
            f"You now have *{user_todays_total_tickets}* ticket(s) registered for today's draw! Good luck! 🍀"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=original_chat_id, 
                message_id=original_message_id, 
                text=confirmation_text_to_user, 
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Edited original payment message for user {user_to_confirm_id} with confirmation.")
        except Exception as edit_e:
            logger.warning(f"Failed to edit original payment message for {user_to_confirm_id}: {edit_e}. Sending a new message instead.")
            await context.bot.send_message(
                chat_id=user_to_confirm_id, 
                text=confirmation_text_to_user, 
                parse_mode=ParseMode.MARKDOWN
            )
        logger.info(f"Payment confirmed for user {user_to_confirm_id}. {num_tickets_purchased} tickets added to their name.")
    except Exception as e:
        logger.error(f"Failed to notify user {user_to_confirm_id} about payment confirmation: {e}")

    if update.message:
        await update.message.reply_text(f"✅ Payment confirmed successfully for User ID `{user_to_confirm_id}`. {num_tickets_purchased} tickets have been added.")


@admin_only
async def manual_winner_draw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER_ADMIN: manual_winner_draw_command invoked.")
    if not update.message: return

    await update.message.reply_text("⏳ Triggering manual winner draw for the previous day's tickets...")
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    logger.info(f"Admin triggered manual draw for date: {yesterday.isoformat()}")
    
    await perform_winner_draw(context, date_override=yesterday) 
    
    await update.message.reply_text("Manual winner draw process has been completed. Please check the bot logs for details.")
    logger.info("Manual winner draw process finished via admin command.")


# --- Scheduled Jobs ---
async def perform_winner_draw(context: ContextTypes.DEFAULT_TYPE, date_override: datetime.date | None = None) -> None:
    draw_date = date_override if date_override else (datetime.date.today() - datetime.timedelta(days=1))
    logger.info(f"SCHEDULER: Starting winner draw process for tickets of date: {draw_date.isoformat()}")

    actual_prize_amount_for_draw = await calculate_prize_for_date(draw_date)
    logger.info(f"SCHEDULER: Calculated total prize for {draw_date.isoformat()} draw: {actual_prize_amount_for_draw:.2f} USDT")

    if actual_prize_amount_for_draw <= Decimal("0.00"):
        logger.info(f"SCHEDULER: No prize pool available for {draw_date.isoformat()} (prize is {actual_prize_amount_for_draw:.2f} USDT). No winner will be drawn.")
        broadcast_text_no_winner = (
            f"🗓️ Daily Draw Results for {draw_date.isoformat()} 🗓️\n\n"
            f"No tickets were sold for this date, so there was no prize pool for this draw.\n"
            f"Don't miss out! Buy your tickets today for a chance to win in tomorrow's draw!"
        )
        user_ids_to_notify = await get_all_user_telegram_ids()
        if user_ids_to_notify:
            await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text_no_winner)
        return

    ticket_entries_for_draw = await get_daily_ticket_entries_for_draw(draw_date)
    if not ticket_entries_for_draw:
        logger.warning(f"SCHEDULER: Prize pool is > 0 for {draw_date.isoformat()} ({actual_prize_amount_for_draw:.2f} USDT), but no ticket entries were found in the database. This indicates a potential inconsistency. No winner declared.")
        try:
            await context.bot.send_message(ADMIN_ID, f"⚠️ CRITICAL WARNING: Inconsistency in draw for {draw_date.isoformat()}. Prize pool was {actual_prize_amount_for_draw:.2f} USDT, but NO ticket entries found. Please investigate the `daily_tickets` table for this date.")
        except Exception as e_admin_warn:
            logger.error(f"Failed to send inconsistency warning to admin: {e_admin_warn}")
        return

    weighted_ticket_list = []
    for entry in ticket_entries_for_draw:
        if entry.get('telegram_id') and isinstance(entry.get('count'), int) and entry['count'] > 0:
            weighted_ticket_list.extend([entry['telegram_id']] * entry['count'])
    
    if not weighted_ticket_list:
        logger.info(f"SCHEDULER: Ticket entries were found for {draw_date.isoformat()}, but the weighted list is empty after processing. No winner can be declared.")
        return

    logger.debug(f"SCHEDULER: Total weighted entries for draw on {draw_date.isoformat()}: {len(weighted_ticket_list)}")
    winner_telegram_id = random.choice(weighted_ticket_list)
    winner_user_data = await get_user(winner_telegram_id) 

    winner_name_display = f'User {winner_telegram_id}' 
    winner_username_display = 'N/A'
    if winner_user_data:
        winner_name_display = winner_user_data.get('first_name', winner_name_display)
        winner_username_display = winner_user_data.get('username', winner_username_display)
    
    logger.info(f"SCHEDULER: Winner selected for {draw_date.isoformat()}: User ID {winner_telegram_id} ({winner_name_display} @{winner_username_display})")

    await simulate_send_usdt(f"Winner ID: {winner_telegram_id}", actual_prize_amount_for_draw, "Winner Prize Payout")
    
    await add_winner_record(winner_telegram_id, actual_prize_amount_for_draw, draw_date)

    broadcast_text_winner = (
        f"🎉🏆 **Daily Draw Results for {draw_date.isoformat()}** 🏆🎉\n\n"
        f"And the winner is... **{winner_name_display}** (@{winner_username_display})!\n\n"
        f"Congratulations! You have won *{actual_prize_amount_for_draw:.2f} USDT*!\n\n"
        f"Thank you to everyone who participated. Buy your tickets today for the next exciting draw!"
    )
    user_ids_to_notify = await get_all_user_telegram_ids()
    if user_ids_to_notify:
        await broadcast_message_to_users_list(context, user_ids_to_notify, broadcast_text_winner, parse_mode=ParseMode.MARKDOWN)
    
    logger.info(f"SCHEDULER: Winner {winner_telegram_id} successfully processed and announced for {draw_date.isoformat()} with prize {actual_prize_amount_for_draw:.2f} USDT")


async def send_daily_marketing_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("SCHEDULER: Starting send_daily_marketing_message_job.")
    message_content = await get_random_marketing_message_content()
    
    if not message_content:
        logger.warning("SCHEDULER: No marketing messages found in the database. Skipping daily marketing message.")
        return

    logger.info("SCHEDULER: Sending daily marketing message to all users...")
    user_ids = await get_all_user_telegram_ids()
    if not user_ids:
        logger.info("SCHEDULER: No users found to send the marketing message to.")
        return
    
    await broadcast_message_to_users_list(context, user_ids, message_content) 
    logger.info("SCHEDULER: Daily marketing message job completed.")


# --- Winners History Command ---
async def winners_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("HANDLER: winners_command invoked.")
    if not update.message: return

    latest_real_winners = await get_latest_winners(limit=7) 
    winners_list_text = "🏆 **TrustWin Bot - Latest Winners** 🏆\n\n"

    if not latest_real_winners:
        winners_list_text += "No winners recorded yet! Be the first to make history!\n"
    else:
        for i, winner_entry in enumerate(latest_real_winners):
            win_date_str = str(winner_entry.get('win_date', 'Unknown Date')) 
            try:
                parsed_date = datetime.date.fromisoformat(win_date_str)
                win_date_display = parsed_date.strftime("%Y-%m-%d") 
            except ValueError:
                win_date_display = win_date_str 
            
            amount_str = str(winner_entry.get('amount', '0')) 
            amount = Decimal(amount_str).quantize(Decimal("0.01"))
            
            user_info = winner_entry.get('user_info')
            name_display = f"User {winner_entry.get('telegram_id', 'Unknown ID')}" 
            if user_info:
                name_display = user_info.get('first_name', name_display)
            
            winners_list_text += f"{i+1}. 🗓️ {win_date_display}: *{name_display}* won *{amount:.2f} USDT*\n"
            
    winners_list_text += "\nBuy a ticket today for your chance to be on this list!"
    await update.message.reply_text(winners_list_text, parse_mode=ParseMode.MARKDOWN)
    logger.info("Winners list displayed.")


# --- Error Handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"ERROR_HANDLER: Exception while handling an update: {context.error}", exc_info=context.error)
    
    try:
        error_summary = str(context.error)[:1000] 
        
        update_details_summary = "Update data not available or too complex."
        if isinstance(update, Update) and update.effective_message:
            update_details_summary = f"Message ID: {update.effective_message.message_id}, Chat ID: {update.effective_message.chat_id}, Text: '{str(update.effective_message.text)[:200]}'"
        elif isinstance(update, Update) and update.callback_query:
            update_details_summary = f"Callback Query ID: {update.callback_query.id}, Data: '{str(update.callback_query.data)[:200]}'"
        elif isinstance(update, Update):
             update_details_summary = str(update)[:1000]
        else:
             update_details_summary = str(type(update))[:1000]

        error_message_to_admin = (
            f"🚨 **Bot Error Alert!** 🚨\n\n"
            f"Error Type: `{type(context.error).__name__}`\n"
            f"Error: `{error_summary}`\n\n"
            f"Update Type: `{type(update).__name__}`\n"
            f"Update Details: `{update_details_summary}`\n\n"
            f"Please check the bot logs for the full traceback."
        )
        if ADMIN_ID: 
            await context.bot.send_message(chat_id=ADMIN_ID, text=error_message_to_admin, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"ERROR_HANDLER: Error notification sent to admin {ADMIN_ID}.")
        else:
            logger.warning("ERROR_HANDLER: ADMIN_ID not set. Cannot send error notification to admin.")

    except Exception as e_notify:
        logger.error(f"CRITICAL_ERROR_HANDLER: Failed to send error notification to admin {ADMIN_ID}. Original error: {context.error}. Notification attempt error: {e_notify}")


# --- Main Function ---
def main() -> None:
    logger.info("STAGE MAIN_0: main() function started.")
    logger.info("Attempting to start TrustWin Bot...")
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("STAGE MAIN_1: Telegram Application built successfully.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to build Telegram Application: {e}. Bot cannot start. Exiting.")
        exit(1)

    job_queue = application.job_queue
    if not job_queue:
        logger.critical("FATAL: No job queue obtained from application. Scheduled tasks cannot run. Bot cannot start reliably. Exiting.")
        exit(1)
    logger.info("STAGE MAIN_2: Job queue obtained successfully.")

    try:
        timezone = pytz.timezone(TIMEZONE_STR)
        logger.info(f"STAGE MAIN_3: Scheduler timezone set to: {TIMEZONE_STR} ({timezone})")
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: '{TIMEZONE_STR}'. Defaulting scheduler to UTC.")
        timezone = pytz.utc 
        logger.info(f"STAGE MAIN_3.1: Scheduler timezone defaulted to UTC.")

    logger.debug("STAGE MAIN_4: Adding command and callback handlers.")
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
    logger.info("STAGE MAIN_4.1: All handlers added.")

    logger.debug("STAGE MAIN_5: Scheduling daily jobs.")
    job_queue.run_daily(perform_winner_draw, time=datetime.time(hour=0, minute=1, second=0, tzinfo=timezone), name="daily_winner_draw")
    logger.info(f"Scheduled daily winner draw at 00:01 ({timezone}) for previous day's tickets.")
    
    job_queue.run_daily(send_daily_marketing_message_job, time=datetime.time(hour=9, minute=0, second=0, tzinfo=timezone), name="daily_marketing_message")
    logger.info(f"Scheduled daily marketing message at 09:00 ({timezone}).")
    logger.info("STAGE MAIN_5.1: Daily jobs scheduled.")

    logger.info("STAGE MAIN_FINAL: Bot is starting to poll for updates...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Bot polling failed critically: {e}. Bot has stopped.")
    
    logger.info("Bot polling has ended.")

if __name__ == '__main__':
    logger.info("STAGE SCRIPT_EXEC: __name__ == '__main__', calling main().")
    main()
    logger.info("STAGE SCRIPT_END: main() function finished or script is ending.")
