Create a full, production-ready Python Telegram bot named "TrustWin Bot" using `python-telegram-bot` version 20+ with the following complete functionality:

1. Bot Type: USDT-based crypto lottery system.
2. Language: Python 3 (async-based), compatible with Render deployment and `run_polling()`.

🔹 Basic Setup:
- Use `ApplicationBuilder` and `run_polling()` (no webhook).
- Store sensitive values (e.g., BOT_TOKEN, ADMIN_ID, USDT_WALLET, SUPABASE_URL, SUPABASE_KEY) in environment variables.
- Use `python-dotenv` or `os.getenv()` for loading secrets.
- Logging and error handling included.

🔹 Key Features:

✅ 1. **User Join & Welcome**
- `/start` command saves user in Supabase DB if new.
- Sends welcome message with referral info.

✅ 2. **Referral System**
- One-level referral system.
- When a user joins with a referral link (`/start <ref_id>`), it saves the referrer and pays 50% of ticket price to the referrer instantly in USDT (TRC-20).
- Each user can invite unlimited people.
- Lifetime passive income to the referrer.

✅ 3. **Ticket Purchase**
- `/buy` command shows ticket price (1 USDT) and wallet address.
- User clicks "I have paid" button to confirm.
- Once admin verifies (manual or auto), ticket is counted.

✅ 4. **Daily Winner Draw**
- At exactly 12:01 AM IST, a random winner is picked from the ticket holders (for that day).
- Winner gets reward in USDT instantly (TRC-20), and name is saved in Supabase `winners` table.
- All users notified daily about the winner.

✅ 5. **Fake History Display**
- `/winners` command shows last 7 fake+real winners in a formatted list (to build trust).
- Add fake entries when no one wins.

✅ 6. **Admin Panel (Simple in Telegram)**
- Only ADMIN_ID can use:
    - `/stats`: See total users, total tickets today.
    - `/users`: List of active users.
    - `/broadcast <message>`: Send message to all users.
    - `/winner`: Manually trigger winner pick.

✅ 7. **Marketing Automation**
- Send daily motivational message to all users at 9 AM IST.
- Messages stored in Supabase and sent using `asyncio`.

✅ 8. **Database (Supabase)**
- Use Supabase as backend.
- Tables:
    - `users`: id, name, username, referrer_id, join_date
    - `tickets`: user_id, ticket_count, date
    - `referrals`: referrer_id, referred_id
    - `winners`: user_id, amount, date
    - `messages`: daily messages

✅ 9. **USDT Transaction System**
- Use TronGrid API or mock function to simulate sending USDT TRC-20.
- Send referral reward and winner prize instantly.

✅ 10. **Security**
- All critical credentials use env vars.
- Error handling, retry logic in requests, and uptime logging.

📦 Deployment:
- Fully compatible with [Render.com] using `run_polling()`.
- Free plan friendly (no webhook).
- Start command: `python bot.py`

🎯 Objective:
- Build a passive income Telegram bot that users trust.
- Easy referral earning + crypto lottery.

Write the full clean code with folders if needed (like `handlers`, `utils`, `services`), in a single file version if possible.
