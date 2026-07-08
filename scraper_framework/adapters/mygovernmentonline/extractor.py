from typing import Any

from bs4 import BeautifulSoup


def extract_records(cards: list[BeautifulSoup]) -> list[dict[str, Any]]:
    permits: list[dict[str, Any]] = []
    for card in cards:
        text = card.get_text(" ", strip=True)
        if not text:
            continue

        permits.append(
            {
                "record_number": card.get("data-record-number"),
                "description": text[:400],
                "status": card.get("data-status"),
                "address": card.get("data-address"),
            }
        )
    return permits
