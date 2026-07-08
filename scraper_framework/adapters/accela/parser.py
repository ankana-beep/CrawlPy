from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def parse_rows(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    print("Parsing search results table...")

    table_elements = soup.select("#ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList")
    if not table_elements:
        print("No data table found on the page.")
        return []

    records: list[dict[str, Any]] = []
    for table_element in table_elements:
        rows = table_element.select("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue

            try:
                date_span = cells[1].find("span")
                date = date_span.text.strip() if date_span else None

                record_num = None
                record_link = None
                link_tag = cells[2].find("a")
                if link_tag:
                    raw_link = link_tag.get("href", "").strip()
                    record_link = urljoin(source_url, raw_link) if raw_link else None

                    span_tag = link_tag.find("span")
                    record_num = span_tag.text.strip() if span_tag else link_tag.text.strip()
                else:
                    span_tag = cells[2].find("span")
                    record_num = span_tag.text.strip() if span_tag else cells[2].get_text(" ", strip=True)

                type_span = cells[3].find("span")
                record_type = type_span.text.strip() if type_span else None

                project_span = cells[4].find("span")
                project_name = project_span.text.strip() if project_span else None

                desc_span = cells[5].find("span")
                description = desc_span.text.strip() if desc_span else None

                address_span = cells[6].find("span")
                address = address_span.text.strip() if address_span else None

                status_div = cells[8].find(id=lambda value: value and value.endswith("panelStatus"))
                status = status_div.text.strip() if status_div else None

                records.append(
                    {
                        "date": date,
                        "record_number": record_num,
                        "detail_link": record_link,
                        "record_type": record_type,
                        "project_name": project_name,
                        "description": description,
                        "address": address,
                        "status": status or "N/A",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Error parsing row elements: {exc}. Skipping row fields.")
                continue

    print(f"Successfully scraped {len(records)} records from page.")
    return records
