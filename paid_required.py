from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
from datetime import datetime

def paid_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        # Ensure user is logged in
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=url_for('dashboard.view')))

        # Check payment status
        if not current_user.is_paid:
            flash("Your access has expired. Please renew your code or make a payment.", "warning")
            return redirect(url_for('auth.apply_code'))

        return f(*args, **kwargs)
    return wrapped