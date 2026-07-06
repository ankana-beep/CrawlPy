"""MongoDB persistence for smart crawl runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

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

    def save_records(self, docs: Iterable[Dict[str, Any]], collection: str) -> Tuple[int, int]:
        inserted = 0
        skipped = 0
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
                skipped += 1
                continue
            self.mongo.db[collection].insert_one(payload)
            inserted += 1
        return inserted, skipped

    def close(self) -> None:
        self.mongo.close()
