from bs4 import BeautifulSoup


def parse_scripts(soup: BeautifulSoup) -> list[str]:
    contents: list[str] = []
    for script in soup.find_all("script"):
        content = script.string or ""
        if content:
            contents.append(content)
    return contents
