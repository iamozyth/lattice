from abc import ABC, abstractmethod
from typing import Any, Dict, List


class Connector(ABC):
    """Abstract base class for data connectors."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required configuration/env is present."""
        raise NotImplementedError

    @abstractmethod
    def connect(self) -> None:
        """Establish any required session/auth."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch data records from the external system."""
        raise NotImplementedError
