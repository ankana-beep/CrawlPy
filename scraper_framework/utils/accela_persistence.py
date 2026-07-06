"""Helpers for persisting Accela harvest results."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from pymongo import UpdateOne
except ImportError as exc:  # pragma: no cover
    raise ImportError("pymongo is required. Install with: pip install -r scraper_framework/requirements.txt") from exc

from scraper_framework.db.mongo_client import MongoDBClient


def collect_downloaded_csv_paths(result: Dict[str, Any]) -> List[str]:
    paths: List[str] = []

    direct_path = result.get("downloaded_csv_path")
    if direct_path:
        paths.append(str(direct_path))

    for run in result.get("runs", []):
        run_path = run.get("downloaded_csv_path")
        if run_path:
            paths.append(str(run_path))

    deduped: List[str] = []
    seen = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def read_csv_rows(csv_path: str) -> List[Dict[str, str]]:
    path = Path(csv_path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def cleanup_csv_files(csv_paths: List[str]) -> None:
    for csv_path in csv_paths:
        path = Path(csv_path)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            continue


def _build_record_docs(result: Dict[str, Any], target: str, csv_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    harvested_at = datetime.now(timezone.utc)

    for file_payload in csv_payload:
        csv_path = file_payload["path"]
        category = Path(csv_path).stem.replace("_results", "").replace("_", " ").strip()
        for row in file_payload["rows"]:
            record_number = _extract_record_number(row)
            row_signature = _build_row_signature(category, row)
            doc = {
                "target": target,
                "site": "accela_building",
                "permit_type_keyword": result.get("permit_type_keyword", "Residential"),
                "category": category,
                "record_number": record_number,
                "row_signature": row_signature,
                "source_csv_path": csv_path,
                "harvested_at": harvested_at,
            }
            normalized_row = {key: value for key, value in row.items() if key and str(key).strip()}
            doc.update(normalized_row)
            docs.append(doc)

    return docs


def _extract_record_number(row: Dict[str, str]) -> str:
    candidates = [
        "Record Number",
        "record_number",
        "RecordNumber",
        "Permit Number",
        "permit_number",
    ]
    for key in candidates:
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""


def _build_row_signature(category: str, row: Dict[str, str]) -> str:
    serialized = json.dumps(
        {
            "category": category,
            "row": row,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _upsert_many_documents(
    mongo: MongoDBClient,
    docs: List[Dict[str, Any]],
    collection: str,
    key_fields: List[str],
) -> int:
    operations = []
    for doc in docs:
        payload = dict(doc)
        created_at = payload.setdefault("created_at", datetime.now(timezone.utc))
        key = {
            field: payload.get(field, "")
            for field in key_fields
        }
        set_payload = {field: value for field, value in payload.items() if field != "created_at"}
        operations.append(
            UpdateOne(
                key,
                {
                    "$set": set_payload,
                    "$setOnInsert": {"created_at": created_at},
                },
                upsert=True,
            )
        )

    if not operations:
        return 0

    result = mongo.db[collection].bulk_write(operations, ordered=False)
    return result.upserted_count + result.modified_count


def persist_accela_result(mongo: MongoDBClient, result: Dict[str, Any], target: str) -> Dict[str, Any]:
    csv_paths = collect_downloaded_csv_paths(result)
    csv_payload = [
        {
            "path": csv_path,
            "rows": read_csv_rows(csv_path),
        }
        for csv_path in csv_paths
    ]
    record_docs = _build_record_docs(result, target, csv_payload)
    inserted_records = _upsert_many_documents(
        mongo,
        record_docs,
        collection="accela_building_records",
        key_fields=["target", "category", "record_number", "row_signature"],
    )

    harvest_doc = {
        "target": target,
        "site": "accela_building",
        "mode": result.get("mode", "single_search"),
        "permit_type_keyword": result.get("permit_type_keyword", "Residential"),
        "csv_file_count": len(csv_payload),
        "record_count": inserted_records,
        "csv_paths": [item["path"] for item in csv_payload],
        "raw": result,
    }
    harvest_id = mongo.insert_raw_scrape(harvest_doc, collection="accela_building_harvests")
    cleanup_csv_files(csv_paths)
    return {
        "harvest_id": harvest_id,
        "record_count": inserted_records,
        "csv_file_count": len(csv_payload),
    }
