"""HTTP fetcher with metadata capture."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Optional

from curl_cffi import requests
from curl_cffi.requests.exceptions import CertificateVerifyError

from scraper_framework.smart_crawler.models import FetchResult

SYSTEM_CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/usr/local/share/certs/ca-root-nss.crt",
)


class SmartHTTPFetcher:
    def __init__(self, *, timeout_seconds: int, user_agent: str, proxies: Optional[Dict[str, str]] = None):
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.proxies = proxies or {}

    def fetch(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        *,
        verify: bool | str = True,
    ) -> FetchResult:
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            **(headers or {}),
        }
        started = time.monotonic()
        response = requests.get(
            url,
            headers=request_headers,
            timeout=self.timeout_seconds,
            proxies=self.proxies,
            allow_redirects=True,
            verify=verify,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        content_type = response.headers.get("content-type", "")
        headers_out = {str(key).lower(): str(value) for key, value in response.headers.items()}
        body_bytes = response.content
        body_text = None
        if _is_textual(content_type, url):
            body_text = response.text
        return FetchResult(
            url=url,
            final_url=response.url,
            status_code=response.status_code,
            headers=headers_out,
            content_type=content_type,
            body_text=body_text,
            body_bytes=body_bytes,
            elapsed_ms=elapsed_ms,
        )


def system_ca_bundle_path() -> Optional[str]:
    for env_name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        candidate = os.getenv(env_name)
        if candidate and Path(candidate).is_file():
            return candidate

    for candidate in SYSTEM_CA_BUNDLE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def is_ssl_certificate_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, CertificateVerifyError):
            return True
        message = str(current).lower()
        if "ssl certificate problem" in message or "certificate verify" in message or "local issuer certificate" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_textual(content_type: str, url: str) -> bool:
    lowered = content_type.lower()
    return (
        lowered.startswith("text/")
        or "json" in lowered
        or "xml" in lowered
        or "javascript" in lowered
        or url.lower().endswith((".html", ".htm", ".json", ".xml", ".txt", ".csv"))
    )
