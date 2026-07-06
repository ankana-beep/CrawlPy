"""Playwright browser client with stealth and persistent context."""

from typing import Any, Dict, Optional
from playwright.sync_api import sync_playwright, Browser, Page

from scraper_framework.config.settings import settings

from .base_client import BaseClient


class PlaywrightClient(BaseClient):
    def __init__(self, user_data_dir: Optional[str] = None, headless: bool = True):
        self.playwright = sync_playwright().start()
        if user_data_dir:
            self.context = self.playwright.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless)
            self.browser = self.context.browser
        else:
            self.browser: Browser = self.playwright.chromium.launch(headless=headless)
            self.context = self.browser.new_context()
        self.page: Page = self.context.new_page()

    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        timeout_ms: Optional[int] = None,
        wait_until: Optional[str] = None,
        **kwargs,
    ) -> str:
        self.page.set_extra_http_headers(headers or {})
        timeout_ms = int(timeout_ms or settings.playwright_timeout_ms)
        wait_until = wait_until or settings.playwright_wait_until

        # Some sites keep long-polling connections open, so waiting for "networkidle"
        # can hang. Default to "domcontentloaded" and optionally try to reach
        # "networkidle" after navigation.
        self.page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        return self.page.content()

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()
