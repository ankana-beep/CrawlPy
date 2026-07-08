from bs4 import BeautifulSoup

from .constants import SIGNATURES


def is_match(url: str, html: str, soup: BeautifulSoup) -> bool:
    haystack = f"{url}\n{html}".lower()
    return any(signature in haystack for signature in SIGNATURES)
