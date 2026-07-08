from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import (
    MONGODB_DB,
    MONGODB_HOST,
    MONGODB_PARAMS,
    MONGODB_PASSWORD,
    MONGODB_SRV,
    MONGODB_USERNAME,
)


class MongoStore:
    def __init__(self) -> None:
        self.client = MongoClient(self._build_uri())
        self.db = self.client[MONGODB_DB]

    def _build_uri(self) -> str:
        scheme = "mongodb+srv" if MONGODB_SRV else "mongodb"
        if MONGODB_USERNAME and MONGODB_PASSWORD:
            username = quote_plus(MONGODB_USERNAME)
            password = quote_plus(MONGODB_PASSWORD)
            auth = f"{username}:{password}@"
        else:
            auth = ""

        uri = f"{scheme}://{auth}{MONGODB_HOST}"
        if MONGODB_PARAMS:
            uri = f"{uri}/?{MONGODB_PARAMS}"
        return uri

    def _collection(self, name: str) -> Collection:
        return self.db[name]

    def create_run(
        self,
        source_url: str,
        adapter_name: str,
        county_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> Any:
        payload = {
            "source_url": source_url,
            "adapter_name": adapter_name,
            "county_name": county_name,
            "agency_key": agency_key,
            "module_name": module_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "error": None,
        }
        result = self._collection("crawl_runs").insert_one(payload)
        return result.inserted_id

    def complete_run(self, run_id: Any, status: str, error: str | None = None) -> None:
        self._collection("crawl_runs").update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": status,
                    "finished_at": datetime.now(timezone.utc),
                    "error": error,
                }
            },
        )

    def log(self, run_id: Any, level: str, message: str, context: dict[str, Any] | None = None) -> None:
        self._collection("crawl_logs").insert_one(
            {
                "run_id": run_id,
                "level": level,
                "message": message,
                "context": context or {},
                "timestamp": datetime.now(timezone.utc),
            }
        )

    def save_source(
        self,
        source_url: str,
        adapter_name: str,
        county_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> None:
        self._collection("sources").update_one(
            {"source_url": source_url},
            {
                "$set": {
                    "source_url": source_url,
                    "adapter_name": adapter_name,
                    "county_name": county_name,
                    "agency_key": agency_key,
                    "module_name": module_name,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    def save_permit(
        self,
        county_name: str | None,
        agency_key: str | None,
        module_name: str | None,
        source_url: str,
        adapter_name: str,
        normalized_data: dict[str, Any],
        raw_data: dict[str, Any],
        crawl_status: str,
    ) -> None:
        self._collection("permits").insert_one(
            {
                "county_name": county_name,
                "agency_key": agency_key,
                "module_name": module_name,
                "source_url": source_url,
                "adapter_name": adapter_name,
                "crawl_timestamp": datetime.now(timezone.utc),
                "normalized_data": normalized_data,
                "raw_data": raw_data,
                "crawl_status": crawl_status,
            }
        )

    def save_raw_result_batch(
        self,
        county_name: str | None,
        agency_key: str | None,
        module_name: str | None,
        source_url: str,
        adapter_name: str,
        raw_items: list[dict[str, Any]],
    ) -> None:
        self._collection("raw_permit_batches").insert_one(
            {
                "county_name": county_name,
                "agency_key": agency_key,
                "module_name": module_name,
                "source_url": source_url,
                "adapter_name": adapter_name,
                "crawl_timestamp": datetime.now(timezone.utc),
                "record_count": len(raw_items),
                "raw_items": raw_items,
            }
        )
