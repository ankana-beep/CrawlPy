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
    db_url: Optional[str] = None
    db_pool_size: int = 5
    supabase_key: Optional[str] = None
    supabase_rest_url: Optional[str] = None
    supabase_text_column: str = "text"
    supabase_json_column: Optional[str] = "json_data"


default_db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("SUPABASE_URL") or os.getenv("DATABASE_URL")

settings = Settings(
    proxies=[],
    user_agents=[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    ],
    db_url=default_db_url,
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_rest_url=os.getenv("SUPABASE_REST_URL"),
    supabase_text_column=os.getenv("SUPABASE_TEXT_COLUMN", "text"),
    supabase_json_column=os.getenv("SUPABASE_JSON_COLUMN", "json_data") or None,
)
