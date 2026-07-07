"""MongoDB persistence for smart crawl runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bson import BSON

from scraper_framework.db.mongo_client import MongoDBClient

MAX_SAFE_BSON_BYTES = 15_000_000


class CrawlMongoStore:
    def __init__(self, mongo: Optional[MongoDBClient] = None):
        self.mongo = mongo or MongoDBClient()

    def save_artifact(self, doc: Dict[str, Any], collection: str) -> Tuple[Any, bool]:
        payload = dict(doc)
        payload.setdefault("created_at", datetime.now(timezone.utc))
        payload = _fit_artifact_for_mongo(payload)
        existing = self.mongo.db[collection].find_one(
            {
                "url": payload.get("url"),
                "content_fingerprint": payload.get("content_fingerprint"),
            },
            {"_id": 1},
        )
        if existing:
            return existing["_id"], False
        return self.mongo.db[collection].insert_one(payload).inserted_id, True

    def save_failure(self, doc: Dict[str, Any], collection: str) -> Any:
        payload = dict(doc)
        payload.setdefault("created_at", datetime.now(timezone.utc))
        return self.mongo.db[collection].insert_one(payload).inserted_id

    def save_records(self, docs: Iterable[Dict[str, Any]], collection: str) -> Tuple[int, int, List[Any]]:
        inserted = 0
        duplicates = 0
        record_ids: List[Any] = []
        for doc in docs:
            payload = dict(doc)
            payload.setdefault("created_at", datetime.now(timezone.utc))
            existing = self.mongo.db[collection].find_one(
                {
                    "record_key": payload.get("record_key"),
                    "record_fingerprint": payload.get("record_fingerprint"),
                },
                {"_id": 1},
            )
            if existing:
                payload["is_duplicate"] = True
                payload["duplicate_of_id"] = existing["_id"]
                payload["duplicate_detected_at"] = datetime.now(timezone.utc)
                duplicates += 1
            else:
                payload["is_duplicate"] = False
            inserted_id = self.mongo.db[collection].insert_one(payload).inserted_id
            record_ids.append(inserted_id)
            inserted += 1
        return inserted, duplicates, record_ids

    def close(self) -> None:
        self.mongo.close()


def _fit_artifact_for_mongo(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _bson_size(payload) <= MAX_SAFE_BSON_BYTES:
        return payload

    slim = dict(payload)
    warnings = list(slim.get("storage_warnings") or [])
    warnings.append("artifact_pruned_before_insert_because_bson_was_too_large")
    slim["storage_warnings"] = warnings

    http = dict(slim.get("http") or {})
    for key in ("body_text", "body_base64"):
        http.pop(key, None)
    http["body_stored"] = False
    http["body_storage_reason"] = "pruned_before_mongo_insert"
    slim["http"] = http

    extracted = dict(slim.get("extracted") or {})
    extracted.pop("raw_html", None)
    slim["extracted"] = extracted

    browser = dict(slim.get("browser") or {})
    for key in ("rendered_html", "screenshot_base64"):
        browser.pop(key, None)
    rendered_extracted = dict(browser.get("rendered_extracted") or {})
    rendered_extracted.pop("raw_html", None)
    browser["rendered_extracted"] = rendered_extracted
    browser["network_calls"] = [_slim_network_call(call) for call in browser.get("network_calls", [])[:500]]
    slim["browser"] = browser

    if _bson_size(slim) <= MAX_SAFE_BSON_BYTES:
        return slim

    browser = dict(slim.get("browser") or {})
    browser["network_calls"] = []
    slim["browser"] = browser
    warnings = list(slim.get("storage_warnings") or [])
    warnings.append("artifact_network_calls_pruned_before_insert_because_bson_was_still_too_large")
    slim["storage_warnings"] = warnings
    return slim


def _slim_network_call(call: Dict[str, Any]) -> Dict[str, Any]:
    slim = dict(call)
    for key in ("body_base64", "post_data_base64", "post_data"):
        slim.pop(key, None)
    return slim


def _bson_size(payload: Dict[str, Any]) -> int:
    try:
        return len(BSON.encode(payload))
    except Exception:
        return MAX_SAFE_BSON_BYTES + 1
