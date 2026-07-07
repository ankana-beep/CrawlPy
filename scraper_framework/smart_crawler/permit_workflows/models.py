"""Data contracts for permit workflow automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class PermitWorkflowOptions:
    date_lookback_days: int = 365
    max_detail_pages: int = 25
    max_pages: int = 5
    timeout_ms: int = 60000
    wait_until: str = "domcontentloaded"
    headless: bool = True
    user_agent: str = ""


@dataclass(slots=True)
class PermitWorkflowResult:
    ran: bool = False
    portal_type: str = "generic"
    actions: List[Dict[str, Any]] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    detail_urls: List[str] = field(default_factory=list)
    network_urls: List[str] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ran": self.ran,
            "portal_type": self.portal_type,
            "actions": self.actions,
            "records": self.records,
            "detail_urls": self.detail_urls,
            "network_urls": self.network_urls,
            "failures": self.failures,
        }
