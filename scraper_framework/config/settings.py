"""Application settings and credentials."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Settings:
    proxies: List[str] = field(default_factory=list)
    user_agents: List[str] = field(default_factory=list)
    api_key_2captcha: Optional[str] = None
    db_url: Optional[str] = None
    db_pool_size: int = 5


settings = Settings(
    proxies=[],
    user_agents=[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    ],
)
