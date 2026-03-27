"""
encryption.py — Application-level symmetric encryption for raw SMS text.

Storage strategy
----------------
raw_sms is stored as BYTEA (LargeBinary) in PostgreSQL.
On INSERT  → plaintext is encrypted with Fernet before it reaches the DB.
On SELECT  → ciphertext is decrypted back to plaintext after the DB returns it.

The pgcrypto extension is enabled in the Alembic migration and is available
for any future SQL-level queries that need it. Fernet was chosen for the ORM
layer because it works transparently with both PostgreSQL and the SQLite
in-memory database used in tests, without requiring PostgreSQL-specific SQL.

Key requirements
----------------
ENCRYPTION_KEY must be a 32-byte URL-safe base64 string:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If ENCRYPTION_KEY is absent or invalid the data is stored as raw UTF-8 bytes
(development convenience).  Production deployments must always set a valid key.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator


def _make_fernet(key: str) -> Fernet | None:
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


class EncryptedText(TypeDecorator):
    """
    SQLAlchemy TypeDecorator that transparently encrypts/decrypts a text
    column using Fernet symmetric encryption.

    Maps to BYTEA (LargeBinary) in PostgreSQL and BLOB in SQLite.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, encryption_key: str = "") -> None:
        super().__init__()
        self._fernet = _make_fernet(encryption_key)

    def process_bind_param(self, value: str | None, dialect) -> bytes | None:
        """Python → DB: encrypt the plaintext before storage."""
        if value is None:
            return None
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if self._fernet is None:
            return raw  # no key configured — store as-is (dev/test fallback)
        return self._fernet.encrypt(raw)

    def process_result_value(self, value: bytes | None, dialect) -> str | None:
        """DB → Python: decrypt the ciphertext after retrieval."""
        if value is None:
            return None
        if self._fernet is None:
            return value.decode("utf-8") if isinstance(value, bytes) else value
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except (InvalidToken, Exception):
            # Fallback: return raw bytes decoded — handles legacy unencrypted rows
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def make_encrypted_text_type() -> EncryptedText:
    """
    Returns an EncryptedText instance initialised with the ENCRYPTION_KEY
    from app settings.  Called at model definition time.
    """
    from app.config import settings  # deferred import to avoid circular imports
    return EncryptedText(encryption_key=settings.ENCRYPTION_KEY)
