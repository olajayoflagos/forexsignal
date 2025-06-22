from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import os
import threading
import asyncio
from flask import Flask, redirect, url_for, jsonify
from flask_wtf import CSRFProtect
from firestore_config import initialize_firestore, db
from firebase_admin import firestore
from auth import auth, login_manager
from dashboard import dashboard
from forum import forum
from news import news
from settings import settings
from scanner import scan_signals_once
import logging

from user import User

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug("Debug logging is working")

load_dotenv()
print(f"Loaded PRICE_NGN: {os.getenv('PRICE_NGN', '0')}")

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    logger.error("SECRET_KEY not set in .env")
    raise ValueError("SECRET_KEY must be set in .env")
logger.debug("Loaded SECRET_KEY: %s", app.secret_key)
logger.debug("Loaded PRICE_NGN: %s", os.getenv("PRICE_NGN", "0"))

csrf = CSRFProtect(app)

try:
    initialize_firestore()
    logger.debug("Firebase initialized successfully")
except Exception as e:
    logger.error("Firebase initialization failed: %s", e)
    raise

login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'

def _start_scanner():
    try:
        asyncio.run(scan_signals_once())
    except Exception as e:
        logger.error("Scanner thread failed: %s", e)

threading.Thread(target=_start_scanner, daemon=True).start()

app.register_blueprint(auth, url_prefix='/auth')
app.register_blueprint(dashboard, url_prefix='/')
app.register_blueprint(forum, url_prefix='/forum')
app.register_blueprint(news, url_prefix='/news')
app.register_blueprint(settings, url_prefix='/settings')

@app.route('/')
def home():
    return redirect(url_for('dashboard.view'))

# API endpoint for signals
@app.route('/api/signals', methods=['GET'])
def get_signals():
    signals = [d.to_dict() for d in db.collection('signals')
                             .order_by('time', direction=firestore.Query.DESCENDING)
                             .limit(20)
                             .stream()]
    return jsonify(signals)

@app.route('/admin/grant_access/<uid>', methods=['POST'])
def grant_access(uid):
    user = User.get(uid)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    user.has_paid = True
    user.paid_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    user.code_issued = "ACCESS1234"  # Or use random code as above
    user.code_expires = user.paid_until
    user.save()

    try:
        from auth import send_email
        send_email(
            to=user.email,
            subject='Your ForexSignal Access Code',
            body=f'Your 30-day access code is: {user.code_issued}'
        )
        logger.debug(f"Email sent successfully to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return jsonify({"message": "Access granted, but email failed. Contact support.", "code": user.code_issued}), 200

    return jsonify({"message": "Access granted successfully", "code": user.code_issued}), 200

if __name__ == '__main__':
    #app.run(debug=True, host='0.0.0.0', port=5000)
    app = Flask(__name__)