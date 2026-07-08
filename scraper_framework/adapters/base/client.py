from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from config.settings import REQUEST_TIMEOUT_SECONDS, get_random_user_agent


@dataclass(slots=True)
class AdapterClients:
    adapter_name: str
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS
    user_agent: str = field(default_factory=get_random_user_agent)
    _requests_session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "X-CrawlPy-Adapter": self.adapter_name,
            }
        )
        self._requests_session = session

    @property
    def requests(self) -> requests.Session:
        return self._requests_session

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.request_timeout_seconds)
        return self._requests_session.get(url, **kwargs)

    def rotate_user_agent(self) -> str:
        self.user_agent = get_random_user_agent()
        self._requests_session.headers.update({"User-Agent": self.user_agent})
        return self.user_agent

    def build_httpx_client(self, **kwargs: Any) -> Any:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "httpx is not installed. Add it to requirements before using adapter HTTPX clients."
            ) from exc

        headers = {"User-Agent": self.user_agent, "X-CrawlPy-Adapter": self.adapter_name}
        kwargs["headers"] = {**headers, **kwargs.get("headers", {})}
        kwargs.setdefault("timeout", self.request_timeout_seconds)
        return httpx.Client(**kwargs)

    def build_async_httpx_client(self, **kwargs: Any) -> Any:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "httpx is not installed. Add it to requirements before using adapter HTTPX clients."
            ) from exc

        headers = {"User-Agent": self.user_agent, "X-CrawlPy-Adapter": self.adapter_name}
        kwargs["headers"] = {**headers, **kwargs.get("headers", {})}
        kwargs.setdefault("timeout", self.request_timeout_seconds)
        return httpx.AsyncClient(**kwargs)

    def build_playwright(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "playwright is not installed. Add it to requirements before using adapter browser clients."
            ) from exc

        return sync_playwright()

    def build_async_playwright(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "playwright is not installed. Add it to requirements before using adapter browser clients."
            ) from exc

        return async_playwright()

    def build_browser_context(self, browser: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("user_agent", self.user_agent)
        return browser.new_context(**kwargs)

    async def build_async_browser_context(self, browser: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("user_agent", self.user_agent)
        return await browser.new_context(**kwargs)
