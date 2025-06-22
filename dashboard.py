from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
import firestore_config
from firebase_admin import firestore
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

dashboard = Blueprint('dashboard', __name__)

# Use the synced paid_required decorator
from paid_required import paid_required

@dashboard.route('/')
@dashboard.route('/dashboard')
@paid_required
def view():
    # Retrieve the latest 20 signals from Firestore
    signals = [d.to_dict() for d in firestore_config.db.collection('signals')
                              .order_by('time', direction=firestore.Query.DESCENDING)
                              .limit(20)
                              .stream()]
    logger.debug("Fetched %d signals for user %s", len(signals), current_user.id)
    return render_template('dashboard.html', signals=signals)