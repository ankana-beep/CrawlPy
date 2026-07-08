from typing import Any


def extract_records(page_text: str) -> list[dict[str, Any]]:
    if not page_text:
        return []
    return [{"description": page_text, "record_type": "permit"}]
