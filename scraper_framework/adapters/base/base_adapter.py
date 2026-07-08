from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests
from bs4 import BeautifulSoup

from config.settings import REQUEST_TIMEOUT_SECONDS, USER_AGENT


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

    def fetch_html(self, url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.text

    def parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    @abstractmethod
    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {field: raw.get(field) for field in CANONICAL_FIELDS}
