import asyncio
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
        self.raw_batches: list[list[dict[str, Any]]] = []
        self.workflow = AccelaPlaywrightWorkflow(
            request_timeout_ms=self.client.request_timeout_seconds * 1000
        )

    def fetch_html(self, url: str) -> str:
        return asyncio.run(self._fetch_html_async(url))

    async def _fetch_html_async(self, url: str) -> str:
        self.raw_batches = []
        async with self.client.build_async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not self.headed)
            context = await self.client.build_async_browser_context(browser)
            page = await context.new_page()
            html = await self.workflow.run(page, url)
            self.raw_batches = [
                parse_rows(BeautifulSoup(page_html, "html.parser"), url)
                for page_html in self.workflow.result_pages_html
            ]
            await context.close()
            await browser.close()
            return html

    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        return is_match(url, html, soup)

    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        if self.raw_batches:
            return [row for batch in self.raw_batches for row in batch]
        rows = parse_rows(soup, url)
        return extract_records(rows)

    def get_raw_batches(self) -> list[list[dict[str, Any]]]:
        return self.raw_batches

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        normalized = super().normalize(raw)
        normalized["issue_date"] = raw.get("issue_date") or raw.get("date")
        normalized["description"] = raw.get("description") or raw.get("project_name")
        normalized["record_number"] = raw.get("record_number")
        normalized["status"] = raw.get("status")
        normalized["address"] = raw.get("address")
        normalized["record_type"] = raw.get("record_type")
        return normalized
