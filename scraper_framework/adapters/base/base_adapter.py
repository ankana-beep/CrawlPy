from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from bs4 import BeautifulSoup

from adapters.base.client import AdapterClients


CANONICAL_FIELDS = [
    "record_number",
    "status",
    "address",
    "record_type",
    "description",
    "issue_date",
    "applicant",
    "contractor",
    "owner",
    "parcel",
    "valuation",
]


class BaseAdapter(ABC):
    name = "base"
    client_class = AdapterClients

    def __init__(self) -> None:
        self.client = self.client_class(adapter_name=self.name)

    def fetch_html(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    def parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def parse(self, html: str) -> BeautifulSoup:
        return self.parse_html(html)

    @abstractmethod
    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {field: raw.get(field) for field in CANONICAL_FIELDS}
