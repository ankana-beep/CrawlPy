"""Data contracts for the smart crawler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CrawlTarget:
    url: str
    depth: int = 0
    source: str = "seed"
    parent_url: Optional[str] = None
    priority: int = 0


@dataclass(slots=True)
class CrawlFailure:
    stage: str
    message: str
    url: str
    retryable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "url": self.url,
            "retryable": self.retryable,
            "details": self.details,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status_code: Optional[int]
    headers: Dict[str, str]
    content_type: str
    body_text: Optional[str] = None
    body_bytes: Optional[bytes] = None
    elapsed_ms: Optional[int] = None


@dataclass(slots=True)
class BrowserResult:
    final_url: str
    rendered_html: str
    text: str
    title: Optional[str]
    cookies: List[Dict[str, Any]]
    local_storage: Dict[str, str]
    session_storage: Dict[str, str]
    network_calls: List[Dict[str, Any]]
    console_messages: List[Dict[str, Any]]
    screenshot_bytes: Optional[bytes] = None


@dataclass(slots=True)
class ExtractedPage:
    url: str
    title: Optional[str]
    text: str
    meta: Dict[str, Any]
    links: List[str]
    feeds: List[str]
    sitemaps: List[str]
    files: List[str]
    api_candidates: List[str]
    embedded_json: List[Dict[str, Any]]
    tables: List[Dict[str, Any]]
    forms: List[Dict[str, Any]]
    emails: List[str]
    phones: List[str]
    raw_html: Optional[str] = None


@dataclass(slots=True)
class CrawlOptions:
    max_pages: int = 50
    max_depth: int = 2
    same_domain_only: bool = True
    include_browser: bool = True
    include_sitemaps: bool = True
    include_feeds: bool = True
    include_files: bool = True
    respect_robots_txt: bool = True
    request_timeout_seconds: int = 30
    delay_seconds: float = 1.0
    max_retries: int = 3
    backoff_seconds: float = 1.5
    collection: str = "permit_crawl_artifacts"
    failure_collection: str = "smart_crawl_failures"
    run_id: Optional[str] = None
    user_agent: Optional[str] = None
    save_raw_html: bool = True
    save_binary_files: bool = False
    browser_screenshot: bool = False
    browser_headless: bool = True
    objective: str = "building_permits"
    prioritize_objective: bool = True
    permit_collection: str = "building_permits"
    collection_per_domain: bool = True
    save_crawl_artifacts: bool = False
    enable_permit_workflows: bool = True
    workflow_date_lookback_days: int = 365
    workflow_max_detail_pages: int = 25
    workflow_max_pages: int = 5


@dataclass(slots=True)
class CrawlStats:
    queued: int = 0
    visited: int = 0
    saved: int = 0
    failed: int = 0
    skipped: int = 0
    duplicates: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "queued": self.queued,
            "visited": self.visited,
            "saved": self.saved,
            "failed": self.failed,
            "skipped": self.skipped,
            "duplicates": self.duplicates,
        }
