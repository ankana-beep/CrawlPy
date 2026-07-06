"""Helper utilities for scraping."""

import random
import time
from typing import Any, Dict, Iterable, List, Optional


def jitter_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def rotate_proxy(proxies: Iterable[str], index: int = 0) -> Optional[Dict[str, str]]:
    proxy_list = list(proxies)
    if not proxy_list:
        return None
    selected = proxy_list[index % len(proxy_list)]
    return {
        "http": selected,
        "https": selected,
    }


def merge_headers(defaults: Dict[str, str], overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    return {**defaults, **(overrides or {})}
