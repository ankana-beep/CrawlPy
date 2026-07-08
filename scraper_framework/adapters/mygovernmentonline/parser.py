from bs4 import BeautifulSoup


def parse_cards(soup: BeautifulSoup) -> list[BeautifulSoup]:
    return soup.select(".permit-card, .record-card, article")
