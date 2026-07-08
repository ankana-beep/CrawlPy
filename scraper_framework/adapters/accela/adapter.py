from typing import Any

from bs4 import BeautifulSoup

from adapters.base.base_adapter import BaseAdapter

from .client import AccelaAdapterClient
from .constants import ADAPTER_NAME
from .detector import is_match
from .extractor import extract_records
from .parser import parse_rows
from .workflow import AccelaPlaywrightWorkflow


class AccelaAdapter(BaseAdapter):
    name = ADAPTER_NAME
    client_class = AccelaAdapterClient

    def __init__(self, headed: bool = False) -> None:
        super().__init__()
        self.headed = headed
        self.workflow = AccelaPlaywrightWorkflow(
            request_timeout_ms=self.client.request_timeout_seconds * 1000
        )

    def fetch_html(self, url: str) -> str:
        with self.client.build_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not self.headed)
            context = self.client.build_browser_context(browser)
            page = context.new_page()
            html = self.workflow.run(page, url)
            context.close()
            browser.close()
            return html

    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        return is_match(url, html, soup)

    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows = parse_rows(soup, url)
        return extract_records(rows)
