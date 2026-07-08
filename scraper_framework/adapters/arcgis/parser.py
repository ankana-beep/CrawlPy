from bs4 import BeautifulSoup


def parse_page(soup: BeautifulSoup) -> str:
    return soup.get_text(" ", strip=True)[:400]
