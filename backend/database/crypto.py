"""
Credential encryption at rest — Fernet symmetric encryption.

All broker credentials (api_key, secret, access_token, refresh_token) must be
encrypted before being stored in the database.  A single DB exfiltration
must NOT yield usable credentials.

Setup (one-time):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Copy the output and add to .env:
    CREDENTIAL_ENCRYPTION_KEY=<paste key here>

If the env var is absent, a WARNING is emitted and a deterministic machine-derived
key is used — suitable for local dev only, NOT for production.

Usage:
    from database.crypto import encrypt_credential, decrypt_credential

    # Before writing to DB:
    db_account.api_key = encrypt_credential(raw_api_key)

    # After reading from DB:
    live_api_key = decrypt_credential(db_account.api_key)
"""

import os
import hashlib
import base64
import warnings
from typing import Optional

_KEY_ENV = "CREDENTIAL_ENCRYPTION_KEY"
_fernet  = None    # module-level singleton; lazy-initialized


def _build_fernet():
    global _fernet
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        warnings.warn(
            "[Security] 'cryptography' package not installed. "
            "Broker credentials will be stored in plaintext. "
            "Run: pip install cryptography",
            stacklevel=3,
        )
        return None

    raw = os.getenv(_KEY_ENV, "")
    if raw:
        key = raw.encode() if isinstance(raw, str) else raw
    else:
        # Derive a deterministic fallback key from machine identity.
        # This is NOT secure for production — anyone who knows the derivation
        # formula can reconstruct the key.
        warnings.warn(
            f"[Security] {_KEY_ENV} is not set. "
            "Credentials are encrypted with a machine-derived key that is NOT "
            "safe for production. Generate a key and set the env var:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "  # Add to your .env file as CREDENTIAL_ENCRYPTION_KEY=<key>",
            stacklevel=3,
        )
        seed = (
            os.getenv("COMPUTERNAME", "")
            + os.getenv("USERNAME", "")
            + "ai_stock_cred_v1"
        ).encode()
        digest = hashlib.sha256(seed).digest()
        key    = base64.urlsafe_b64encode(digest)

    _fernet = Fernet(key)
    return _fernet


def _get_fernet():
    if _fernet is None:
        _build_fernet()
    return _fernet


def encrypt_credential(plaintext: Optional[str]) -> Optional[str]:
    """
    Encrypt a credential string for database storage.

    Returns the Fernet ciphertext as a UTF-8 string, or the original value
    if the cryptography library is not available (with a warning).
    Returns None/empty unchanged.
    """
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext   # fallback: store plaintext (warned at init)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: Optional[str]) -> Optional[str]:
    """
    Decrypt a stored credential.

    Handles backward-compatible migration path: if the stored value is not a
    valid Fernet token (e.g., it was stored as plaintext before encryption was
    added), it is returned as-is so existing integrations keep working.
    Returns None/empty unchanged.
    """
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        from cryptography.fernet import InvalidToken
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        # Not a valid Fernet token — return as-is (plaintext migration path)
        return ciphertext
