from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ConnectorError(Exception):
    """A connector failed; the message is safe to show."""


class BaseConnector(ABC):
    """A source of hosts. fetch() returns dicts with ip, mac, hostname, vendor, device_type."""

    type: str = ''
    timeout = 10

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @classmethod
    @abstractmethod
    def clean_config(cls, data: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate user input. Blank secrets keep the existing value."""

    @staticmethod
    @abstractmethod
    def public_details(config: Dict[str, Any]) -> Dict[str, Any]:
        """Config fields that are safe to show in the UI."""

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Return the hosts this system knows about."""
