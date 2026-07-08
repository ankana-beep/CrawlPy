from typing import Any

from bs4 import BeautifulSoup

from adapters.base.base_adapter import BaseAdapter

from .client import CivicPlusAdapterClient
from .constants import ADAPTER_NAME
from .detector import is_match
from .extractor import extract_records
from .parser import parse_page


class CivicPlusAdapter(BaseAdapter):
    name = ADAPTER_NAME
    client_class = CivicPlusAdapterClient

    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        return is_match(url, html, soup)

    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        page_title = parse_page(soup)
        return extract_records(page_title)
