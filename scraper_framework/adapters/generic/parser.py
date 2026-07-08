from bs4 import BeautifulSoup


def parse_page(soup: BeautifulSoup) -> dict[str, str | None]:
    title = soup.title.get_text(strip=True) if soup.title else None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = meta_desc.get("content") if meta_desc else None
    return {"title": title, "description": description}
