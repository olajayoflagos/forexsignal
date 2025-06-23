# firebase_config.py

import os
import json
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load .env locally (ignored by Render, but useful for dev)
load_dotenv()

db = None

def initialize_firestore():
    global db
    if not firebase_admin._apps:
        firebase_json = os.getenv("FIREBASE_CONFIG_JSON")
        if not firebase_json:
            raise ValueError("FIREBASE_CONFIG_JSON not found in environment variables.")
        try:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Firebase initialization failed: {e}")
            raise e
    db = firestore.client()
