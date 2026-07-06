"""URL normalization and classification helpers."""

from __future__ import annotations

from typing import Iterable, List, Optional
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse


FILE_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".xls",
    ".xlsx",
    ".json",
    ".xml",
    ".txt",
    ".zip",
}

FEED_HINTS = ("rss", "atom", "feed")
API_HINTS = ("/api/", "/graphql", "/rest/", ".json", "/v1/", "/v2/", "/wp-json/")


def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
    if not url:
        return None
    absolute = urljoin(base_url, url.strip()) if base_url else url.strip()
    clean, _fragment = urldefrag(absolute)
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = parsed.path or "/"
    normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path)
    return urlunparse(normalized)


def same_domain(url: str, seed_domains: Iterable[str]) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname in set(seed_domains)


def domain_for(url: str) -> str:
    return urlparse(url).hostname or ""


def looks_like_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in FILE_EXTENSIONS)


def looks_like_feed(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in FEED_HINTS)


def looks_like_api(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in API_HINTS)


def unique_urls(urls: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out
