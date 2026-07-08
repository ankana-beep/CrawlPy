from typing import Any


def extract_records(rows: list[list[str]]) -> list[dict[str, Any]]:
    permits: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 3:
            continue

        permit: dict[str, Any] = {
            "record_number": cells[0],
            "record_type": cells[1],
            "status": cells[2],
        }
        if len(cells) > 3:
            permit["address"] = cells[3]
        if len(cells) > 4:
            permit["issue_date"] = cells[4]
        permits.append(permit)

    return permits
