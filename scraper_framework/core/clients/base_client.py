"""Abstract base client interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseClient(ABC):
    @abstractmethod
    def fetch(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, data: Any = None, **kwargs) -> Any:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
