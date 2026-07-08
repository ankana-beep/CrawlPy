from typing import Any

from bs4 import BeautifulSoup

from adapters.base.base_adapter import BaseAdapter

from .client import MyGovernmentOnlineAdapterClient
from .constants import ADAPTER_NAME
from .detector import is_match
from .extractor import extract_records
from .parser import parse_cards


class MyGovernmentOnlineAdapter(BaseAdapter):
    name = ADAPTER_NAME
    client_class = MyGovernmentOnlineAdapterClient

    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        return is_match(url, html, soup)

    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards = parse_cards(soup)
        return extract_records(cards)
