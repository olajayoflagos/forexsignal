# firebase_config.py

import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load .env so FIREBASE_CREDENTIALS is available
load_dotenv()

db = None

def initialize_firestore():
    global db
    # only initialize once
    if not firebase_admin._apps:
        cred_path = os.getenv("FIREBASE_CREDENTIALS")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
