from flask_login import UserMixin
import firestore_config
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

class User(UserMixin):
    def __init__(
        self,
        uid: str,
        data: Dict[str, Any]
    ):
        self.id = uid
        self.email = data.get("email")
        self.username = data.get("username")
        self.phone = data.get("phone")
        self.anonymous = data.get("anonymous", False)
        self.code_issued = data.get("code_issued")  # ISO string
        self.code_expires = data.get("code_expires")
        self.has_paid = data.get("has_paid", False)
        self.paid_until = data.get("paid_until")  # Keep for compatibility

    @classmethod
    def get(cls, uid: str) -> Optional["User"]:
        """Load a User by UID from Firestore, or return None if not found."""
        doc = firestore_config.db.collection("users").document(uid).get()
        if not doc.exists:
            return None
        return cls(uid, doc.to_dict())

    def save(self) -> None:
        """Persist this User’s data back to Firestore."""
        firestore_config.db.collection("users").document(self.id).set({
            "email": self.email,
            "username": self.username,
            "phone": self.phone,
            "anonymous": self.anonymous,
            "code_issued": self.code_issued,
            "code_expires": self.code_expires,
            "has_paid": self.has_paid,
            "paid_until": self.paid_until  # Keep for compatibility
        }, merge=True)

    def code_valid(self) -> bool:
        """
        Returns True if the user has paid and their code expiry
        timestamp is still in the future (UTC).
        """
        if not self.has_paid or not self.code_expires:
            return False
        expiry_dt = datetime.fromisoformat(self.code_expires)
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        return expiry_dt > datetime.now(timezone.utc)

    @property
    def is_paid(self) -> bool:
        """Compatibility property for paid_until check."""
        return self.code_valid() if self.code_expires else (self.paid_until and datetime.fromisoformat(self.paid_until) > datetime.now(timezone.utc))