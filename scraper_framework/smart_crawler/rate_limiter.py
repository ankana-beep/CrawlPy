"""Domain-aware polite rate limiter."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict

from scraper_framework.smart_crawler.url_tools import domain_for


class DomainRateLimiter:
    def __init__(self, delay_seconds: float):
        self.delay_seconds = max(0.0, delay_seconds)
        self.last_request_at: Dict[str, float] = defaultdict(float)

    def wait(self, url: str) -> None:
        if self.delay_seconds <= 0:
            return

        domain = domain_for(url)
        elapsed = time.monotonic() - self.last_request_at[domain]
        remaining = self.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_at[domain] = time.monotonic()
