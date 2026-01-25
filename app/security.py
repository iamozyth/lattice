import base64
import json
import os
import hashlib
from typing import Any, Dict

from cryptography.fernet import Fernet


def _derive_key_from_secret(secret: str) -> bytes:
    """Derive a 32-byte urlsafe base64 key from an arbitrary secret string.

    This allows using the app's SECRET_KEY or a dedicated CONNECTOR_SECRET.
    """
    if not secret:
        # Fallback static string (not recommended); caller should ensure a real secret is provided
        secret = "netdoc-ipam-default-secret"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    """Return a Fernet instance using CONNECTOR_SECRET or derive from SECRET_KEY."""
    connector_secret = os.environ.get("CONNECTOR_SECRET")
    if connector_secret and len(connector_secret) >= 32:
        try:
            # If provided as raw 32-byte urlsafe base64 key, use directly
            key = connector_secret.encode("utf-8")
            # Validate by constructing Fernet (will raise if invalid)
            return Fernet(key)
        except Exception:
            # If invalid format, derive from provided string
            pass
        key = _derive_key_from_secret(connector_secret)
        return Fernet(key)

    # Fallback to SECRET_KEY or static derivation
    secret_key = os.environ.get("SECRET_KEY", "")
    key = _derive_key_from_secret(secret_key)
    return Fernet(key)


def encrypt_config(config: Dict[str, Any]) -> bytes:
    """Encrypt a JSON config dict to bytes."""
    f = get_fernet()
    payload = json.dumps(config).encode("utf-8")
    return f.encrypt(payload)


def decrypt_config(blob: bytes) -> Dict[str, Any]:
    """Decrypt bytes back into a JSON dict."""
    f = get_fernet()
    data = f.decrypt(blob)
    return json.loads(data.decode("utf-8"))
