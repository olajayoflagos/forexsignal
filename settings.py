from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
import firestore_config
from user import User  # Import User class
from datetime import datetime
from paid_required import paid_required  # Use synced decorator

settings = Blueprint('settings', __name__, url_prefix='/settings')

@settings.route('/', methods=['GET'])
@paid_required  # Restrict access to paid users
def view():
    user = User.get(current_user.id)  # Fetch full user data
    return render_template('settings.html', user=user)

@settings.route('/profile', methods=['POST'])
@paid_required
def update_profile():
    data = {
        'username': request.form.get('username', ''),
        'email': request.form.get('email', ''),
        'phone': request.form.get('phone', '')
    }
    firestore_config.db.collection('users').document(current_user.id).update(data)
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('settings.view'))

@settings.route('/feedback', methods=['POST'])
@paid_required
def send_feedback():
    feedback = {
        'user_id': current_user.id,
        'subject': request.form.get('subject', ''),
        'message': request.form.get('message', ''),
        'time': datetime.utcnow().isoformat()
    }
    firestore_config.db.collection('feedbacks').add(feedback)
    flash('Thanks! Your feedback has been sent.', 'success')
    return redirect(url_for('settings.view'))