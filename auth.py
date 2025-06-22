import os
import uuid
import datetime
import smtplib
import requests
from email.message import EmailMessage
import logging

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, session, current_app
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash

import firestore_config
from user import User

auth = Blueprint('auth', __name__)
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'

_serializer = URLSafeTimedSerializer(os.getenv("SECRET_KEY"))

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@login_manager.user_loader
def load_user(uid):
    return User.get(uid)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        if data['password'] != data['confirm_password']:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.register'))

        uid = str(uuid.uuid4())
        hashed = generate_password_hash(data['password'])
        firestore_config.db.collection('users').document(uid).set({
            'email': data['email'],
            'username': data['username'],
            'phone': data['phone'],
            'password': hashed,
            'paid_until': None,
            'has_paid': False,
            'code_issued': None,
            'code_expires': None
        })
        session['reg_uid'] = uid
        # Generate a numeric reference based on timestamp
        reference = int(datetime.datetime.now().timestamp())
        session['reg_reference'] = reference  # Save only numeric reference

        # Initialize Paystack payment with requests
        amount_ngn = float(data.get('amount_ngn', 15000))  # Pre-filled from form
        amount_kobo = int(amount_ngn * 100)
        logger.debug(f"Initializing payment with amount_ngn={amount_ngn}, amount_kobo={amount_kobo}, reference={reference}")
        
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {os.getenv('PAYSTACK_SK')}",
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount_kobo,
            "email": data['email'],
            "reference": str(reference),  # Convert to string as Paystack expects a string parameter
            "callback_url": url_for("auth.verify", _external=True)
        }
        logger.debug(f"Paystack payload: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        logger.debug(f"Paystack response: {response.text}")

        resp_data = response.json()
        if not resp_data.get("status"):
            logger.error(f"Paystack init failed: {resp_data.get('message')}")
            flash(f"Payment init failed: {resp_data.get('message', 'Unknown error')}", "danger")
            return redirect(url_for("auth.register"))

        auth_url = resp_data.get("data", {}).get("authorization_url")
        if not auth_url:
            logger.error(f"Missing authorization_url in Paystack resp: {resp_data}")
            flash("Could not retrieve Paystack authorization URL.", "danger")
            return redirect(url_for("auth.register"))

        return redirect(auth_url)  # Redirect to Paystack payment page

    return render_template('register.html')

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']

        query = firestore_config.db.collection('users').where('email', '==', identifier)
        if not list(query.stream()):
            query = firestore_config.db.collection('users').where('username', '==', identifier)
        user_doc = next(query.stream(), None)

        if not user_doc:
            flash('Unknown user.', 'danger')
            return redirect(url_for('auth.login'))

        data = user_doc.to_dict()
        if not check_password_hash(data.get('password', ''), password):
            flash('Incorrect password.', 'danger')
            return redirect(url_for('auth.login'))

        user = User(user_doc.id, data)
        login_user(user, remember=('remember' in request.form))
        return redirect(url_for('dashboard.view'))

    return render_template('login.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth.route('/verify')
def verify():
    reference = session.get('reg_reference')  # Use stored numeric reference
    if not reference:
        logger.error("No transaction reference found in session")
        flash('Verification failed: no transaction reference provided.', 'danger')
        return redirect(url_for('auth.register'))

    url = "https://api.paystack.co/transaction/verify"
    headers = {
        "Authorization": f"Bearer {os.getenv('PAYSTACK_SK')}",
        "Content-Type": "application/json"
    }
    params = {"reference": str(reference)}  # Use the numeric reference as a string
    logger.debug(f"Verifying transaction with params: {params}")
    response = requests.get(url, params=params, headers=headers)
    resp_data = response.json()

    logger.debug(f"Paystack verify response: {resp_data}")
    if resp_data.get("status") and resp_data.get("data", {}).get("status") == "success":
        uid = session.pop('reg_uid', None)
        if not uid:
            logger.error("No registration context found in session")
            flash('Verification failed: no registration context.', 'danger')
            return redirect(url_for('auth.register'))

        paid_until = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
        firestore_config.db.collection('users').document(uid).update({
            'paid_until': paid_until,
            'has_paid': True,
            'code_issued': str(uuid.uuid4())[:8],
            'code_expires': paid_until
        })

        code = firestore_config.db.collection('users').document(uid).get().to_dict()['code_issued']
        user_email = firestore_config.db.collection('users').document(uid).get().to_dict()['email']
        try:
            send_email(
                to=user_email,
                subject='Your ForexSignal Access Code',
                body=f'Your 30-day access code is: {code}'
            )
            logger.debug(f"Email sent successfully to {user_email}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            flash('Payment successful, but email failed to send. Contact support.', 'warning')

        flash('Payment successful! Check your email for your code.', 'success')
        return redirect(url_for('auth.login'))
    else:
        logger.error(f"Verification failed: {resp_data.get('message')}")
        flash('Payment verification done. Contact +2348110249980 via Whatsapp providing your mail address to manually update your login status', 'success')
        return redirect(url_for('auth.register'))

@auth.route('/apply_code', methods=['GET', 'POST'])
def apply_code():
    if request.method == 'POST':
        code = request.form.get('code')
        if not code:
            flash('Please enter an access code.', 'warning')
            return render_template('apply_code.html')

        code_doc = firestore_config.db.collection('codes').document(code).get()
        if not code_doc.exists:
            flash('Invalid or expired access code.', 'danger')
            return render_template('apply_code.html')

        code_data = code_doc.to_dict()
        uid = code_data.get('uid')
        if not uid or uid != current_user.id:
            flash('Access code does not match your account.', 'danger')
            return render_template('apply_code.html')

        paid_until = code_data.get('expires')
        if not paid_until or datetime.fromisoformat(paid_until) < datetime.utcnow():
            flash('Access code has expired.', 'danger')
            return render_template('apply_code.html')

        firestore_config.db.collection('users').document(uid).update({
            'paid_until': paid_until,
            'has_paid': True,
            'code_issued': code,
            'code_expires': paid_until
        })
        firestore_config.db.collection('codes').document(code).delete()

        flash('Access code applied successfully! Your subscription is extended.', 'success')
        return redirect(url_for('dashboard.view'))

    return render_template('apply_code.html')

@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        users = firestore_config.db.collection('users').where('email', '==', email).stream()
        user_doc = next(users, None)
        if not user_doc:
            flash('No account with that email.', 'warning')
            return redirect(url_for('auth.forgot_password'))

        token = _serializer.dumps(email, salt='pw-reset')
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        send_email(
            to=email,
            subject='Reset your ForexSignal password',
            body=f'Click here to reset (valid 1 hr):\n\n{reset_url}'
        )
        flash('Reset link sent—check your email.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')

@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = _serializer.loads(token, salt='pw-reset', max_age=3600)
    except SignatureExpired:
        flash('Reset link expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('Invalid reset token.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        pw = request.form['password']
        pw2 = request.form['confirm_password']
        if not pw or pw != pw2:
            flash('Passwords must match.', 'warning')
            return redirect(request.url)

        hashed = generate_password_hash(pw)
        users = firestore_config.db.collection('users').where('email', '==', email).stream()
        doc = next(users, None)
        if doc:
            firestore_config.db.collection('users').document(doc.id).update({'password': hashed})
            flash('Password reset successful! Please log in.', 'success')
            return redirect(url_for('auth.login'))

        flash('User not found.', 'danger')
        return redirect(url_for('auth.register'))

    return render_template('reset_password.html')

def send_email(to: str, subject: str, body: str):
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = os.getenv('EMAIL_SENDER')
    msg['To'] = to

    server = smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT', 587)))
    server.starttls()
    server.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASS'))
    server.send_message(msg)
    server.quit()