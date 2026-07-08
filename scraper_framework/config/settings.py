from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


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
