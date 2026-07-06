"""Application settings and credentials."""

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Settings:
    proxies: List[str] = field(default_factory=list)
    user_agents: List[str] = field(default_factory=list)
    api_key_2captcha: Optional[str] = None
    supabase_key: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_table: str = "crawl"
    supabase_text_column: str = "text"
    supabase_json_column: Optional[str] = "json_data"
    playwright_timeout_ms: int = 60000
    playwright_wait_until: str = "domcontentloaded"

settings = Settings(
    proxies=[],
    user_agents=[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    ],
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
    supabase_table=os.getenv("SUPABASE_TABLE", "crawl"),
    supabase_text_column=os.getenv("SUPABASE_TEXT_COLUMN", "text"),
    supabase_json_column=os.getenv("SUPABASE_JSON_COLUMN", "json_data") or None,
    playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "60000")),
    playwright_wait_until=os.getenv("PLAYWRIGHT_WAIT_UNTIL", "domcontentloaded"),
)
