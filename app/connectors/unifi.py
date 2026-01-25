import os
import logging
from typing import Any, Dict, List, Optional

import requests

from .base import Connector

logger = logging.getLogger(__name__)


class UniFiConnector(Connector):
    """
    Connector for UniFi Network API to collect connected clients.

    Configuration via environment variables:
    - UNIFI_BASE_URL: Base URL to UniFi OS (e.g., https://unifi.local)
    - UNIFI_USERNAME: Admin username (optional if using UNIFI_API_KEY)
    - UNIFI_PASSWORD: Admin password (optional if using UNIFI_API_KEY)
    - UNIFI_SITE_ID: Site identifier (often 'default')
    - UNIFI_API_KEY: Optional API key/token (if available)
    - UNIFI_VERIFY_SSL: 'true'/'false' (default true)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Default from environment
        self.base_url = os.environ.get("UNIFI_BASE_URL", "").rstrip("/")
        self.username = os.environ.get("UNIFI_USERNAME")
        self.password = os.environ.get("UNIFI_PASSWORD")
        self.site_id = os.environ.get("UNIFI_SITE_ID", "default")
        self.api_key = os.environ.get("UNIFI_API_KEY")
        self.verify_ssl = os.environ.get("UNIFI_VERIFY_SSL", "true").lower() == "true"
        self.session: Optional[requests.Session] = None
        if config:
            self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        self.base_url = (config.get("base_url") or self.base_url or "").rstrip("/")
        self.username = config.get("username") or self.username
        self.password = config.get("password") or self.password
        self.site_id = config.get("site_id") or self.site_id
        self.api_key = config.get("api_key") or self.api_key
        verify = config.get("verify_ssl")
        if verify is not None:
            self.verify_ssl = bool(verify)

    def is_configured(self) -> bool:
        return bool(self.base_url and self.site_id and (self.api_key or (self.username and self.password)))

    def connect(self) -> None:
        if not self.is_configured():
            raise RuntimeError("UniFi connector not configured. Set UNIFI_BASE_URL, UNIFI_SITE_ID and credentials.")

        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        headers = {
            "User-Agent": "NetDoc-IPAM/1.0",
            "Accept": "application/json",
        }

        if self.api_key:
            # If API key present, use Bearer auth
            headers["Authorization"] = f"Bearer {self.api_key}"
            self.session.headers.update(headers)
            return

        # Otherwise, perform login to UniFi OS
        login_url = f"{self.base_url}/api/auth/login"
        payload = {"username": self.username, "password": self.password}
        resp = self.session.post(login_url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"UniFi login failed: {resp.status_code} {resp.text[:200]}")
        logger.info("UniFi login successful")

    def fetch(self) -> List[Dict[str, Any]]:
        if not self.session:
            self.connect()

        # Endpoint to list connected clients. Path can vary per UniFi version; try common proxy path.
        candidates = [
            f"{self.base_url}/proxy/network/api/s/default/stat/sta",  # legacy
            f"{self.base_url}/proxy/network/v2/api/site/{self.site_id}/clients",  # v2 style
        ]

        last_error = None
        for url in candidates:
            try:
                resp = self.session.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and "data" in data:
                        records = data.get("data", [])
                    else:
                        records = data if isinstance(data, list) else []
                    return [self._normalize_client(c) for c in records]
                else:
                    last_error = f"{resp.status_code} {resp.text[:200]}"
            except Exception as e:
                last_error = str(e)

        msg = f"UniFi client fetch failed: {last_error or 'no response'}"
        logger.warning(msg)
        raise RuntimeError(msg)

    def _normalize_client(self, c: Dict[str, Any]) -> Dict[str, Any]:
        """Map UniFi client record to a canonical schema."""
        return {
            "ip": c.get("ip") or c.get("network", {}).get("ip"),
            "mac": c.get("mac") or c.get("mac_address"),
            "hostname": c.get("hostname") or c.get("name") or c.get("host_name"),
            "device_type": c.get("device_type") or "client",
            "manufacturer": c.get("manufacturer") or c.get("oui") or None,
            "notes": c.get("notes") or None,
        }
