from bs4 import BeautifulSoup


def parse_page(soup: BeautifulSoup) -> str:
    title = soup.title.get_text(strip=True) if soup.title else ""
    return title
