"""Application settings and credentials."""

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
USER_AGENT_POOL_PATH = Path(__file__).resolve().with_name("user_agents_pool.txt")


def _load_user_agents() -> List[str]:
    if USER_AGENT_POOL_PATH.exists():
        user_agents = [
            line.strip()
            for line in USER_AGENT_POOL_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if user_agents:
            return user_agents

    return [DEFAULT_USER_AGENT]


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
    playwright_headless: bool = True

    mongodb_uri: Optional[str] = None
    mongodb_srv: bool = True
    mongodb_host: Optional[str] = None
    mongodb_username: Optional[str] = None
    mongodb_password: Optional[str] = None
    mongodb_db: str = "crawlpy"
    mongodb_params: str = ""

    def build_mongodb_uri(self) -> str:
        if self.mongodb_uri:
            return self.mongodb_uri

        if not self.mongodb_host:
            raise ValueError("MongoDB host is required (MONGODB_HOST) when MONGODB_URI is not set.")

        scheme = "mongodb+srv" if self.mongodb_srv else "mongodb"
        auth = ""
        if self.mongodb_username:
            password = quote_plus(self.mongodb_password or "")
            auth = f"{quote_plus(self.mongodb_username)}:{password}@"

        db_path = f"/{self.mongodb_db}" if self.mongodb_db else ""
        params = self.mongodb_params.strip()
        if params and not params.startswith("?"):
            params = "?" + params

        return f"{scheme}://{auth}{self.mongodb_host}{db_path}{params}"

    def get_random_user_agent(self) -> str:
        return random.choice(self.user_agents)

settings = Settings(
    proxies=[],
    user_agents=_load_user_agents(),
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
    supabase_table=os.getenv("SUPABASE_TABLE", "crawl"),
    supabase_text_column=os.getenv("SUPABASE_TEXT_COLUMN", "text"),
    supabase_json_column=os.getenv("SUPABASE_JSON_COLUMN", "json_data") or None,
    playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "60000")),
    playwright_wait_until=os.getenv("PLAYWRIGHT_WAIT_UNTIL", "domcontentloaded"),
    playwright_headless=os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() in {"1", "true", "yes", "y"},
    mongodb_uri=os.getenv("MONGODB_URI"),
    mongodb_srv=os.getenv("MONGODB_SRV", "true").lower() in {"1", "true", "yes", "y"},
    mongodb_host=os.getenv("MONGODB_HOST"),
    mongodb_username=os.getenv("MONGODB_USERNAME"),
    mongodb_password=os.getenv("MONGODB_PASSWORD"),
    mongodb_db=os.getenv("MONGODB_DB", "crawlpy"),
    mongodb_params=os.getenv("MONGODB_PARAMS", ""),
)
