from typing import Any


def extract_records(script_contents: list[str]) -> list[dict[str, Any]]:
    permits: list[dict[str, Any]] = []
    for content in script_contents:
        if "permit" not in content.lower():
            continue
        permits.append(
            {
                "description": content[:400],
                "record_type": "building",
            }
        )
    return permits
