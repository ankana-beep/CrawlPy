"""Playwright browser client with stealth and persistent context."""

from typing import Any, Dict, Optional
from playwright.sync_api import sync_playwright, Browser, Page

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

    def fetch(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, data: Any = None, **kwargs) -> str:
        self.page.set_extra_http_headers(headers or {})
        self.page.goto(url, wait_until="networkidle")
        return self.page.content()

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()
