"""MongoDB client for primary persistence of raw scrape data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from pymongo import MongoClient
    from pymongo import UpdateOne
except ImportError as exc:  # pragma: no cover
    raise ImportError("pymongo is required. Install with: pip install -r scraper_framework/requirements.txt") from exc

from scraper_framework.config.settings import settings


class MongoDBClient:
    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None):
        self.uri = uri or settings.build_mongodb_uri()
        self.db_name = db_name or settings.mongodb_db
        if not self.uri:
            raise ValueError("MongoDB URI is required. Set MONGODB_URI or MONGODB_HOST + credentials.")
        if not self.db_name:
            raise ValueError("MongoDB database name is required (MONGODB_DB).")

        self.client = MongoClient(self.uri)
        self.db = self.client[self.db_name]

    def insert_raw_scrape(self, doc: Dict[str, Any], collection: str = "scrapes") -> Any:
        payload = dict(doc)
        payload.setdefault("created_at", datetime.now(timezone.utc))
        return self.db[collection].insert_one(payload).inserted_id

    def upsert_many_by_id(self, docs: list[Dict[str, Any]], collection: str) -> Dict[str, Any]:
        """Upsert many documents using each doc's `_id`.

        This is intentionally tolerant for batch ingestion:
        - Missing `_id` docs are skipped.
        - Each upsert sets `created_at` on insert and updates fields on every run.
        """

        now = datetime.now(timezone.utc)
        ops: list[UpdateOne] = []
        for doc in docs:
            _id = doc.get("_id")
            if _id is None or _id == "":
                continue

            payload = dict(doc)
            payload.pop("_id", None)
            ops.append(
                UpdateOne(
                    {"_id": _id},
                    {"$set": payload, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
            )

        if not ops:
            return {"ok": 1, "nOps": 0}

        result = self.db[collection].bulk_write(ops, ordered=False)
        return {
            "ok": 1,
            "nOps": len(ops),
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "upserted_count": len(getattr(result, "upserted_ids", {}) or {}),
        }

    def close(self) -> None:
        self.client.close()
