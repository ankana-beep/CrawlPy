from typing import Any


def extract_records(page_data: dict[str, str | None]) -> list[dict[str, Any]]:
    return [
        {
            "record_number": None,
            "status": None,
            "address": None,
            "record_type": "unknown",
            "description": page_data.get("description"),
            "issue_date": None,
            "applicant": None,
            "contractor": None,
            "owner": None,
            "parcel": None,
            "valuation": None,
            "page_title": page_data.get("title"),
        }
    ]
