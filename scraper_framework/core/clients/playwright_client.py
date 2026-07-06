"""Playwright browser client with simple page interaction helpers."""

from typing import Any, Dict, List, Optional
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

    def goto(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
        wait_until: Optional[str] = None,
    ) -> Page:
        self.page.set_extra_http_headers(headers or {})
        timeout_ms = int(timeout_ms or settings.playwright_timeout_ms)
        wait_until = wait_until or settings.playwright_wait_until

        self.page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        return self.page

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
        self.goto(url, headers=headers, timeout_ms=timeout_ms, wait_until=wait_until)
        return self.page.content()

    def wait_for_selector(self, selector: str, timeout_ms: Optional[int] = None) -> None:
        self.page.wait_for_selector(selector, timeout=int(timeout_ms or settings.playwright_timeout_ms))

    def get_select_options(self, selector: str) -> List[Dict[str, str]]:
        options = self.page.locator(f"{selector} option")
        items: List[Dict[str, str]] = []
        for index in range(options.count()):
            option = options.nth(index)
            items.append(
                {
                    "value": option.get_attribute("value") or "",
                    "label": option.inner_text().strip(),
                }
            )
        return items

    def select_option(
        self,
        selector: str,
        value: Optional[str] = None,
        label: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> List[str]:
        if not value and not label:
            raise ValueError("Either value or label is required to select an option.")

        self.wait_for_selector(selector, timeout_ms=timeout_ms)

        selection: Dict[str, str] = {}
        if value:
            selection["value"] = value
        if label:
            selection["label"] = label

        return self.page.locator(selector).select_option(**selection)

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()
