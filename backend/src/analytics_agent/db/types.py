"""SQLAlchemy TypeDecorators for encrypted column storage."""

from __future__ import annotations

import logging

from sqlalchemy.types import Text, TypeDecorator

logger = logging.getLogger(__name__)


class EncryptedJSON(TypeDecorator):
    """Transparent Fernet encryption for Text columns storing JSON.

    Behaviour by configuration:
    - OAUTH_MASTER_KEY set   → encrypt on write, decrypt on read.
    - OAUTH_MASTER_KEY unset → store/read as plaintext (dev / test mode).

    Migration safety:
    - Values that start with 'gAAAAA' are treated as Fernet ciphertext and
      decrypted strictly (raises on failure — don't silently return garbage).
    - All other values are assumed to be legacy plaintext JSON and returned
      as-is, so existing rows survive the transition without a data migration.
    """

    impl = Text
    cache_ok = True

    def _fernet(self):
        from analytics_agent.config import settings

        key = settings.oauth_master_key.strip()
        if not key:
            return None
        from cryptography.fernet import Fernet

        return Fernet(key.encode() if isinstance(key, str) else key)

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        f = self._fernet()
        if f is None:
            return value  # no key configured — store plaintext
        return f.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if value.startswith("gAAAAA"):
            f = self._fernet()
            if f is None:
                msg = (
                    "Context platform config is encrypted but OAUTH_MASTER_KEY is not set. "
                    "Restore the key from your .env file."
                )
                logger.error(msg)
                raise ValueError(msg)
            try:
                return f.decrypt(value.encode()).decode()
            except Exception as exc:
                msg = (
                    "Failed to decrypt context platform config — "
                    "OAUTH_MASTER_KEY may have changed. Restore the original key."
                )
                logger.error(msg)
                raise ValueError(msg) from exc
        # Plaintext JSON — legacy row or no-key mode; return as-is
        return value
