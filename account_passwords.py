"""Argon2id credentials, with verification of the existing PBKDF2 records."""
import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

hasher = PasswordHasher()


def hash_password(password):
    if not isinstance(password, str) or not 6 <= len(password) <= 1024:
        raise ValueError("Password must contain 6–1024 characters.")
    return "", hasher.hash(password)


def verify_password(password, account):
    if not isinstance(password, str) or len(password) > 1024:
        return False
    digest = account.get("password_hash")
    if not isinstance(digest, str) or not digest:
        # An unset hash is never a credential, including for ID login.
        return False
    if digest.startswith("$argon2id$"):
        try:
            return hasher.verify(digest, password)
        except (VerificationError, InvalidHashError):
            return False
    legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), str(account.get("salt", "")).encode(), 120000).hex()
    return secrets.compare_digest(legacy, digest)
