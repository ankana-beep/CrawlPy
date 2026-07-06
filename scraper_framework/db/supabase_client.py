"""Supabase client for saving scraped results."""

from typing import Any, Dict, Optional

from supabase import Client, create_client

from scraper_framework.config.settings import settings


class SupabaseClient:
    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None, table: Optional[str] = None):
        self.url = url or settings.supabase_url
        self.api_key = api_key or settings.supabase_key
        self.table = table or settings.supabase_table

        if not self.url:
            raise ValueError("SUPABASE_URL must be set to use Supabase save.")
        if not self.api_key:
            raise ValueError("SUPABASE_KEY must be set to use Supabase save.")
        if not self.table:
            raise ValueError("SUPABASE_TABLE must be set to use Supabase save.")

        self.client: Client = create_client(self.url, self.api_key)

    def insert(self, payload: Dict[str, Any]) -> Any:
        try:
            result = self.client.table(self.table).insert(payload).execute()
        except Exception as exc:  # supabase-py may raise ApiError/HTTPError depending on version
            raise RuntimeError(f"Supabase insert failed: {exc}") from exc

        error = getattr(result, "error", None)
        if error:
            raise RuntimeError(f"Supabase insert failed: {error}")

        return getattr(result, "data", None)
