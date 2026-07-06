"""Retry helpers for transient crawl failures."""

from __future__ import annotations

import time
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class RetryExhausted(Exception):
    pass


def with_retries(
    operation: Callable[[], T],
    *,
    max_retries: int,
    backoff_seconds: float,
    retryable_exceptions: Iterable[type[BaseException]] = (Exception,),
) -> T:
    attempt = 0
    last_error: BaseException | None = None
    while attempt <= max_retries:
        try:
            return operation()
        except tuple(retryable_exceptions) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            sleep_for = backoff_seconds * (2 ** attempt)
            time.sleep(sleep_for)
            attempt += 1

    raise RetryExhausted(str(last_error)) from last_error
