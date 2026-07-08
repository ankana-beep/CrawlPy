from __future__ import annotations

import os
import random
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
PROJECT_ROOT = BASE_DIR.parent


MONGODB_SRV = os.getenv("MONGODB_SRV", "true").lower() == "true"
MONGODB_HOST = os.getenv("MONGODB_HOST", "localhost")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "")
MONGODB_DB = os.getenv("MONGODB_DB", "crawlpy")
MONGODB_PARAMS = os.getenv("MONGODB_PARAMS", "")

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; CrawlPy/1.0; +https://example.local)",
)
USER_AGENTS_FILE = Path(os.getenv("USER_AGENTS_FILE", PROJECT_ROOT / "user_agents.txt"))


def load_user_agents() -> list[str]:
    if not USER_AGENTS_FILE.exists():
        return [USER_AGENT]

    user_agents = [
        line.strip()
        for line in USER_AGENTS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return user_agents or [USER_AGENT]


USER_AGENTS = load_user_agents()


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)
