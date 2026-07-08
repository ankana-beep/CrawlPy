from typing import Any


def extract_records(page_title: str) -> list[dict[str, Any]]:
    if not page_title:
        return []
    return [{"description": page_title, "record_type": "permit"}]
