"""Lightweight schema helpers for Supabase rows.

This project uses Supabase REST/SDK (no direct Postgres connections), so we keep
these as plain Python types rather than SQLAlchemy models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ScrapedItem:
    """Represents a row in the Supabase `crawl` table."""

    id: Optional[int] = None
    created_at: Optional[datetime] = None
    url: str = ""
    title: Optional[str] = None
    text: Optional[str] = None
    json_data: Optional[Dict[str, Any]] = None

