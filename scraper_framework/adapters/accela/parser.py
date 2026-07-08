from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


TABLE_SELECTORS = [
    "#ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList",
    "#ctl00_PlaceHolderMain_DataGrid",
    ".ACA_GridView",
]


def parse_rows(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    print("Parsing search results table...")

    table_elements = []
    for selector in TABLE_SELECTORS:
        table_elements = soup.select(selector)
        if table_elements:
            print(f"Found result table with selector: {selector}")
            break

    if not table_elements:
        print("No data table found on the page.")
        return []

    records: list[dict[str, Any]] = []
    for table_element in table_elements:
        headers = [
            header.get_text(" ", strip=True)
            for header in table_element.select("tr th")
        ]
        header_map = {header.lower(): index for index, header in enumerate(headers)}
        rows = table_element.select("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            try:
                date = _cell_text(cells, header_map, "date")

                record_num = None
                record_link = None
                record_index = _find_index(header_map, "record number")
                if record_index is not None and record_index < len(cells):
                    link_tag = cells[record_index].find("a")
                    if link_tag:
                        raw_link = link_tag.get("href", "").strip()
                        record_link = urljoin(source_url, raw_link) if raw_link else None

                        span_tag = link_tag.find("span")
                        record_num = span_tag.text.strip() if span_tag else link_tag.get_text(" ", strip=True)
                    else:
                        span_tag = cells[record_index].find("span")
                        record_num = (
                            span_tag.text.strip()
                            if span_tag
                            else cells[record_index].get_text(" ", strip=True)
                        )

                record_type = _cell_text(cells, header_map, "record type")
                project_name = _cell_text(cells, header_map, "project name")
                description = _cell_text(cells, header_map, "description")
                address = _cell_text(cells, header_map, "address")
                status = _cell_text(cells, header_map, "status")
                expiration_date = _cell_text(cells, header_map, "expiration date")
                action = _cell_text(cells, header_map, "action")

                records.append(
                    {
                        "date": date,
                        "record_number": record_num,
                        "detail_link": record_link,
                        "record_type": record_type,
                        "project_name": project_name,
                        "description": description,
                        "address": address,
                        "action": action,
                        "status": status or "N/A",
                        "expiration_date": expiration_date,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Error parsing row elements: {exc}. Skipping row fields.")
                continue

    print(f"Successfully scraped {len(records)} records from page.")
    return records


def _find_index(header_map: dict[str, int], header_name: str) -> int | None:
    return header_map.get(header_name.lower())


def _cell_text(cells: list[Any], header_map: dict[str, int], header_name: str) -> str | None:
    index = _find_index(header_map, header_name)
    if index is None or index >= len(cells):
        return None

    span_tag = cells[index].find("span")
    if span_tag:
        return span_tag.get_text(" ", strip=True)
    return cells[index].get_text(" ", strip=True) or None
