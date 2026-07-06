"""Abstract base parser interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseParser(ABC):
    @abstractmethod
    def parse(self, content: Any, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
