"""Encryption for stored connector credentials."""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, MultiFernet
from flask import current_app

# Earlier versions fell back to this public constant when no secret was set.
# We still accept it for decryption so existing connectors keep working; the
# next save re-encrypts with the real key.
_LEGACY_SECRET = 'netdoc-ipam-default-secret'


def _derive(secret):
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())


def _key_from(secret):
    """CONNECTOR_SECRET may be a Fernet key or any string."""
    try:
        Fernet(secret.encode('utf-8'))
        return secret.encode('utf-8')
    except (ValueError, TypeError):
        return _derive(secret)


def get_fernet():
    connector_secret = current_app.config.get('CONNECTOR_SECRET')
    secret_key = current_app.config['SECRET_KEY']
    keys = []
    if connector_secret:
        keys.append(_key_from(connector_secret))
    keys.append(_derive(secret_key))
    keys.append(_derive(_LEGACY_SECRET))
    return MultiFernet([Fernet(k) for k in dict.fromkeys(keys)])


def encrypt_config(config):
    return get_fernet().encrypt(json.dumps(config).encode('utf-8'))


def decrypt_config(blob):
    return json.loads(get_fernet().decrypt(blob).decode('utf-8'))
