"""Orchestrator for fetch, parse, and save flow."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseService(ABC):
    @abstractmethod
    def run(self, target: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
