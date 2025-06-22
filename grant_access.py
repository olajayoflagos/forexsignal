import os
from datetime import datetime, timezone, timedelta
import firestore_config  # Use absolute import for the renamed file
from user import User
import random  # For generating a unique access code if needed

# Initialize Firestore
firestore_config.initialize_firestore()

# Step 1: Load the user by UID
uid = "f851ff58-3721-487d-828a-f7150ac99184"  # Full UID provided
user = User.get(uid)

if user is None:
    print(f"User with UID {uid} not found.")
else:
    # Step 2: Update user data
    user.has_paid = True
    user.paid_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()  # 30 days from now
    # Option 1: Use a fixed access code
    user.code_issued = "ACCESS1234"
    # Option 2: Generate a unique 8-character code (uncomment if preferred)
    # user.code_issued = ''.join(random.choices('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=8))
    user.code_expires = user.paid_until  # Set expiry to match paid_until

    # Step 3: Save the changes to Firestore
    user.save()
    print(f"User {user.username} (UID: {uid}) has been granted access. Access code: {user.code_issued}, expires on {user.code_expires}.")

    # Step 4: Optional - Send email (uncomment and configure if needed)
    
    from auth import send_email  # Import from your auth.py
    try:
        send_email(
            to=user.email,
            subject='Your ForexSignal Access Code',
            body=f'Your 30-day access code is: {user.code_issued}'
        )
        print(f"Email sent successfully to {user.email}")
    except Exception as e:
        print(f"Failed to send email: {e}")
    