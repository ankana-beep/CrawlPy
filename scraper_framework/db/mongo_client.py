"""MongoDB client for primary persistence of raw scrape data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from pymongo import MongoClient
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

    def close(self) -> None:
        self.client.close()
