"""MongoDB persistence for smart crawl runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from scraper_framework.db.mongo_client import MongoDBClient


class CrawlMongoStore:
    def __init__(self, mongo: Optional[MongoDBClient] = None):
        self.mongo = mongo or MongoDBClient()

    def save_artifact(self, doc: Dict[str, Any], collection: str) -> Tuple[Any, bool]:
        payload = dict(doc)
        payload.setdefault("created_at", datetime.now(timezone.utc))
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
        skipped = 0
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
                record_ids.append(existing["_id"])
                skipped += 1
                continue
            inserted_id = self.mongo.db[collection].insert_one(payload).inserted_id
            record_ids.append(inserted_id)
            inserted += 1
        return inserted, skipped, record_ids

    def close(self) -> None:
        self.mongo.close()
