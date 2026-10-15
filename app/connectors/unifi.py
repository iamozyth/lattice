"""UniFi Network: connected clients from a UniFi OS console or controller."""
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests

from app.connectors.base import BaseConnector, ConnectorError
from app.validation import ValidationError

logger = logging.getLogger(__name__)


class UniFiConnector(BaseConnector):
    type = 'unifi'

    @classmethod
    def clean_config(cls, data, existing=None):
        existing = existing or {}
        base_url = (data.get('base_url') or '').strip().rstrip('/')
        parsed = urlparse(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValidationError('base_url must be an http(s) URL, e.g. https://192.168.1.1')
        site_id = (data.get('site_id') or 'default').strip()
        if not site_id.replace('-', '').replace('_', '').isalnum():
            raise ValidationError('site_id may only contain letters, numbers, - and _')
        config = {
            'base_url': base_url,
            'site_id': site_id,
            'verify_ssl': bool(data.get('verify_ssl', True)),
            'api_key': (data.get('api_key') or '').strip() or existing.get('api_key'),
            'username': (data.get('username') or '').strip() or existing.get('username'),
            'password': data.get('password') or existing.get('password'),
        }
        if data.get('auth') == 'api_key':
            config.update(username=None, password=None)
        elif data.get('auth') == 'password':
            config['api_key'] = None
        if not config['api_key'] and not (config['username'] and config['password']):
            raise ValidationError('Provide an API key, or a username and password')
        return config

    @staticmethod
    def public_details(config):
        return {
            'base_url': config.get('base_url'),
            'site_id': config.get('site_id'),
            'auth': 'api_key' if config.get('api_key') else 'password',
            'username': config.get('username'),
            'verify_ssl': bool(config.get('verify_ssl', True)),
        }

    def _session(self):
        session = requests.Session()
        session.verify = self.config.get('verify_ssl', True)
        session.headers.update({'User-Agent': 'Lattice', 'Accept': 'application/json'})
        base = self.config['base_url']
        if self.config.get('api_key'):
            # UniFi OS API keys use X-API-KEY; older Lattice versions sent a Bearer token
            session.headers['X-API-KEY'] = self.config['api_key']
            session.headers['Authorization'] = f"Bearer {self.config['api_key']}"
            return session
        try:
            resp = session.post(f'{base}/api/auth/login', timeout=self.timeout, allow_redirects=False,
                                json={'username': self.config['username'],
                                      'password': self.config['password']})
        except requests.RequestException as e:
            raise ConnectorError(f'Could not reach {base}: {type(e).__name__}')
        if resp.status_code in (401, 403):
            raise ConnectorError('UniFi rejected the username or password')
        if resp.status_code >= 400:
            raise ConnectorError(f'UniFi login failed with HTTP {resp.status_code}')
        return session

    def fetch(self) -> List[Dict[str, Any]]:
        session = self._session()
        base = self.config['base_url']
        site = quote(self.config['site_id'], safe='')
        candidates = [
            f'{base}/proxy/network/api/s/{site}/stat/sta',   # UniFi OS
            f'{base}/proxy/network/v2/api/site/{site}/clients/active',
            f'{base}/proxy/network/v2/api/site/{site}/clients',
            f'{base}/api/s/{site}/stat/sta',                 # standalone controller
        ]
        status: Optional[int] = None
        for url in candidates:
            try:
                resp = session.get(url, timeout=self.timeout, allow_redirects=False)
            except requests.RequestException as e:
                raise ConnectorError(f'Could not reach {base}: {type(e).__name__}')
            status = resp.status_code
            if status == 200:
                try:
                    payload = resp.json()
                except ValueError:
                    raise ConnectorError('UniFi returned something that is not JSON')
                records = payload.get('data', []) if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise ConnectorError('Unexpected response from UniFi')
                return [self._normalize(c) for c in records if isinstance(c, dict)]
            if status in (401, 403):
                raise ConnectorError('UniFi rejected the credentials')
        raise ConnectorError(f'UniFi client list not found (HTTP {status}). Check the URL and site ID.')

    @staticmethod
    def _normalize(c):
        return {
            'ip': c.get('ip') or c.get('last_ip'),
            'mac': c.get('mac'),
            'hostname': c.get('hostname') or c.get('name'),
            'vendor': c.get('oui') or None,
            'device_type': 'wired' if c.get('is_wired') else 'wireless' if 'is_wired' in c else None,
        }
