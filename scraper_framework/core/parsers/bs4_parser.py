"""HTML parser using BeautifulSoup4."""

from typing import Any, Dict
from bs4 import BeautifulSoup

from .base_parser import BaseParser


class BS4Parser(BaseParser):
    def parse(self, content: str, **kwargs) -> Dict[str, Any]:
        soup = BeautifulSoup(content, "lxml")
        for honeypot in soup.select("input[type=hidden][name*=honeypot], div[class*=honeypot], a[href*=javascript:void]"):
            honeypot.decompose()

        data = {
            "title": soup.title.string.strip() if soup.title and soup.title.string else None,
            "text": soup.get_text(separator=" ", strip=True),
        }
        return data
