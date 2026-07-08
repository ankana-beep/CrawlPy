from bs4 import BeautifulSoup


def parse_rows(soup: BeautifulSoup) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
        if cells:
            rows.append(cells)
    return rows
