# main bot file
# --- Render Health Check Server ---
import threading
from flask import Flask

def run_web():
    app = Flask(__name__)
    @app.route('/')
    def home():
        return 'TrustWin Bot is Running!'
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

threading.Thread(target=run_web).start()
