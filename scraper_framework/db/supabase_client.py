"""Supabase REST client for saving scraped results when Postgres is unreachable."""

from typing import Any, Dict, Optional

import requests

from scraper_framework.config.settings import settings


class SupabaseClient:
    def __init__(self, rest_url: Optional[str] = None, api_key: Optional[str] = None):
        self.rest_url = rest_url or settings.supabase_rest_url
        self.api_key = api_key or settings.supabase_key

        if not self.rest_url:
            raise ValueError("SUPABASE_REST_URL must be set to use Supabase REST save.")
        if not self.api_key:
            raise ValueError("SUPABASE_KEY must be set to use Supabase REST save.")

        self.headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def insert(self, payload: Dict[str, Any]) -> Any:
        response = requests.post(self.rest_url, headers=self.headers, json=payload)
        if not response.ok:
            raise RuntimeError(
                f"Supabase REST insert failed: {response.status_code} {response.reason} - {response.text}"
            )
        return response.json() if response.text else {}
