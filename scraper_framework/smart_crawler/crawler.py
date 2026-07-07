"""Hybrid unauthenticated crawler orchestration."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from scraper_framework.config.settings import settings
from scraper_framework.smart_crawler.browser_collector import BrowserCollector
from scraper_framework.smart_crawler.extractors import GenericExtractor
from scraper_framework.smart_crawler.fetcher import SmartHTTPFetcher
from scraper_framework.smart_crawler.frontier import CrawlFrontier
from scraper_framework.smart_crawler.models import (
    CrawlFailure,
    CrawlOptions,
    CrawlStats,
    CrawlTarget,
    FetchResult,
    utc_now,
)
from scraper_framework.smart_crawler.permit_objective import LEGACY_OBJECTIVE_NAMES, OBJECTIVE_NAME, PermitObjectiveExtractor
from scraper_framework.smart_crawler.rate_limiter import DomainRateLimiter
from scraper_framework.smart_crawler.retry import RETRYABLE_STATUS_CODES, RetryExhausted, with_retries
from scraper_framework.smart_crawler.robots import RobotsGuard, robots_url_for
from scraper_framework.smart_crawler.storage import CrawlMongoStore
from scraper_framework.smart_crawler.url_tools import looks_like_file, looks_like_feed, normalize_url
from scraper_framework.utils.logger import configure_logger


class SmartCrawler:
    """Crawl unknown unauthenticated sites with layered extraction strategies."""

    def __init__(
        self,
        options: Optional[CrawlOptions] = None,
        *,
        store: Optional[CrawlMongoStore] = None,
        browser: Optional[BrowserCollector] = None,
    ):
        self.options = options or CrawlOptions()
        self.options.run_id = self.options.run_id or str(uuid.uuid4())
        self.user_agent = self.options.user_agent or settings.get_random_user_agent()
        self.store = store
        self.extractor = GenericExtractor()
        self.objective_extractor = (
            PermitObjectiveExtractor()
            if self.options.objective in {OBJECTIVE_NAME, *LEGACY_OBJECTIVE_NAMES}
            else None
        )
        self.fetcher = SmartHTTPFetcher(timeout_seconds=self.options.request_timeout_seconds, user_agent=self.user_agent)
        self.rate_limiter = DomainRateLimiter(self.options.delay_seconds)
        self.robots = RobotsGuard(self.user_agent, enabled=self.options.respect_robots_txt)
        self.browser = browser
        self.logger = configure_logger("scraper_framework.smart_crawler")

    @property
    def run_id(self) -> str:
        return str(self.options.run_id)

    def crawl(self, urls: Iterable[str], *, save: bool = True) -> Dict[str, Any]:
        seeds = [url for url in (normalize_url(url) for url in urls) if url]
        frontier = CrawlFrontier(seeds, same_domain_only=self.options.same_domain_only)
        stats = CrawlStats(queued=len(frontier))
        artifact_saved_ids: List[str] = []
        permit_records_saved = 0
        permit_records_duplicate = 0
        used_collections: set[str] = set()
        used_permit_collections: set[str] = set()

        self.logger.info(
            "Starting permit crawl run_id=%s objective=%s prioritize_objective=%s seeds=%s max_pages=%s max_depth=%s save=%s save_artifacts=%s browser=%s same_domain_only=%s robots=%s collection_per_domain=%s",
            self.run_id,
            self.options.objective,
            self.options.prioritize_objective,
            len(seeds),
            self.options.max_pages,
            self.options.max_depth,
            save,
            self.options.save_crawl_artifacts,
            self.options.include_browser,
            self.options.same_domain_only,
            self.options.respect_robots_txt,
            self.options.collection_per_domain,
        )
        for seed in seeds:
            self.logger.info("Seed queued: %s", seed)

        if save and self.store is None:
            self.logger.info(
                "Opening MongoDB store permit_collection_base=%s artifact_collection_base=%s failures_base=%s",
                self.options.permit_collection,
                self.options.collection,
                self.options.failure_collection,
            )
            self.store = CrawlMongoStore()

        try:
            while len(frontier) and stats.visited < self.options.max_pages:
                target = frontier.pop()
                if target is None:
                    break
                if target.url in frontier.visited:
                    continue

                if not self.robots.allowed(target.url):
                    stats.skipped += 1
                    stats.queued = len(frontier)
                    robots_url = robots_url_for(target.url)
                    self.logger.info(
                        "Skipped by robots.txt depth=%s source=%s url=%s robots_url=%s hint='use --ignore-robots only when you have permission'",
                        target.depth,
                        target.source,
                        target.url,
                        robots_url,
                    )
                    self._record_failure(
                        CrawlFailure(
                            stage="robots",
                            message="Blocked by robots.txt",
                            url=target.url,
                            retryable=False,
                            details={
                                "target": asdict(target),
                                "robots_url": robots_url,
                                "override_flag": "--ignore-robots",
                                "override_note": "Use only when you have permission to crawl this site.",
                            },
                        ),
                        save=save,
                    )
                    continue

                frontier.visited.add(target.url)
                stats.visited += 1
                self.logger.info(
                    "Visiting %s/%s depth=%s queued=%s source=%s url=%s",
                    stats.visited,
                    self.options.max_pages,
                    target.depth,
                    len(frontier),
                    target.source,
                    target.url,
                )
                try:
                    artifact = self._crawl_target(target, frontier)
                    if save and self.store:
                        permit_collection = self._collection_for_url(self.options.permit_collection, artifact.get("final_url") or target.url)
                        saved_permits, skipped_permits, permit_record_ids = self._save_objective_records(artifact, permit_collection)
                        artifact["permit_collection"] = permit_collection
                        artifact["permit_record_ids"] = [str(record_id) for record_id in permit_record_ids]
                        permit_records_saved += saved_permits
                        permit_records_duplicate += skipped_permits
                        stats.saved += saved_permits
                        stats.duplicates += skipped_permits
                        if saved_permits:
                            used_permit_collections.add(permit_collection)
                            self.logger.info(
                                "Saved standardized permit records inserted=%s duplicate_skipped=%s collection=%s url=%s",
                                saved_permits,
                                skipped_permits,
                                permit_collection,
                                target.url,
                            )
                        elif skipped_permits:
                            used_permit_collections.add(permit_collection)
                            self.logger.info(
                                "Skipped duplicate permit records count=%s collection=%s url=%s",
                                skipped_permits,
                                permit_collection,
                                target.url,
                            )
                        else:
                            self.logger.info("No permit-level records found to save url=%s", target.url)

                        if self.options.save_crawl_artifacts:
                            collection = self._collection_for_url(self.options.collection, artifact.get("final_url") or target.url)
                            used_collections.add(collection)
                            inserted_id, inserted = self._save_artifact(artifact, collection)
                            if inserted:
                                artifact_saved_ids.append(str(inserted_id))
                                self.logger.info("Saved debug artifact id=%s collection=%s url=%s", inserted_id, collection, target.url)
                            else:
                                stats.duplicates += 1
                                self.logger.info("Skipped duplicate debug artifact existing_id=%s collection=%s url=%s", inserted_id, collection, target.url)
                except Exception as exc:
                    stats.failed += 1
                    self.logger.exception("Crawl failed url=%s error=%s", target.url, exc)
                    self._record_failure(
                        CrawlFailure(
                            stage="crawl",
                            message=str(exc),
                            url=target.url,
                            retryable=True,
                            details={"target": asdict(target), "exception_type": type(exc).__name__},
                        ),
                        save=save,
                    )

                stats.queued = len(frontier)
                self.logger.info(
                    "Progress run_id=%s visited=%s saved=%s duplicates=%s failed=%s skipped=%s queued=%s",
                    self.run_id,
                    stats.visited,
                    stats.saved,
                    stats.duplicates,
                    stats.failed,
                    stats.skipped,
                    stats.queued,
                )

            result = {
                "run_id": self.run_id,
                "stats": stats.as_dict(),
                "artifact_saved_ids": artifact_saved_ids,
                "permit_records_saved": permit_records_saved,
                "permit_records_duplicate": permit_records_duplicate,
                "collections": sorted(used_collections) if save else [],
                "permit_collections": sorted(used_permit_collections) if save and self.objective_extractor else [],
            }
            self.logger.info("Finished smart crawl run_id=%s stats=%s", self.run_id, stats.as_dict())
            return result
        finally:
            if self.browser is not None:
                self.logger.info("Closing browser collector")
                self.browser.close()
            if self.store is not None:
                self.logger.info("Closing MongoDB store")
                self.store.close()

    def _crawl_target(self, target: CrawlTarget, frontier: CrawlFrontier) -> Dict[str, Any]:
        self.logger.info("Rate limit wait domain/url=%s delay_seconds=%s", target.url, self.options.delay_seconds)
        self.rate_limiter.wait(target.url)
        self.logger.info("HTTP fetch start url=%s timeout_seconds=%s", target.url, self.options.request_timeout_seconds)
        fetch_result = self._fetch_with_retry(target.url)
        body_size = len(fetch_result.body_bytes or b"") if fetch_result.body_bytes is not None else 0
        self.logger.info(
            "HTTP fetch done status=%s elapsed_ms=%s content_type=%s bytes=%s final_url=%s",
            fetch_result.status_code,
            fetch_result.elapsed_ms,
            fetch_result.content_type or "unknown",
            body_size,
            fetch_result.final_url,
        )

        artifact: Dict[str, Any] = {
            "artifact_key": self._artifact_key(target.url, "page"),
            "run_id": self.run_id,
            "artifact_type": "page",
            "target": asdict(target),
            "url": target.url,
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "headers": fetch_result.headers,
            "content_type": fetch_result.content_type,
            "elapsed_ms": fetch_result.elapsed_ms,
            "crawled_at": utc_now(),
            "http": self._http_payload(fetch_result),
            "browser": None,
            "extracted": None,
            "discovered": {"links": [], "files": [], "feeds": [], "sitemaps": [], "api_candidates": []},
            "objective": None,
            "failures": [],
        }

        if _is_http_error(fetch_result):
            raise RuntimeError(f"HTTP status {fetch_result.status_code}")

        if _is_html(fetch_result) and fetch_result.body_text:
            extracted = self.extractor.extract_html(
                fetch_result.body_text,
                fetch_result.final_url,
                include_raw=self.options.save_raw_html,
            )
            artifact["extracted"] = asdict(extracted)
            queued_links = self._queue_discoveries(extracted.links, target, frontier, "link")
            self._queue_optional_discoveries(extracted, target, frontier)
            artifact["objective"] = self._extract_objective_from_page(extracted, source_url=fetch_result.final_url)
            artifact["discovered"] = {
                "links": extracted.links,
                "files": extracted.files,
                "feeds": extracted.feeds,
                "sitemaps": extracted.sitemaps,
                "api_candidates": extracted.api_candidates,
            }
            self.logger.info(
                "Extracted HTML title=%r text_chars=%s links=%s queued_links=%s files=%s feeds=%s sitemaps=%s api_candidates=%s forms=%s tables=%s embedded_json=%s objective_score=%s objective_records=%s",
                extracted.title,
                len(extracted.text or ""),
                len(extracted.links),
                queued_links,
                len(extracted.files),
                len(extracted.feeds),
                len(extracted.sitemaps),
                len(extracted.api_candidates),
                len(extracted.forms),
                len(extracted.tables),
                len(extracted.embedded_json),
                (artifact["objective"] or {}).get("score"),
                (artifact["objective"] or {}).get("record_count"),
            )

            if self.options.include_browser and self._should_render(extracted):
                self.logger.info("Browser render selected url=%s reason=low_text_or_forms_or_app_shell", target.url)
                try:
                    artifact["browser"] = self._collect_browser_with_retry(target, frontier)
                except RetryExhausted as exc:
                    self.logger.warning(
                        "Browser render skipped after retries url=%s attempts=%s error=%s",
                        target.url,
                        self.options.max_retries + 1,
                        exc,
                    )
                    artifact["failures"].append(
                        {
                            "stage": "browser_render",
                            "message": str(exc),
                            "retryable": False,
                            "attempts": self.options.max_retries + 1,
                        }
                    )
            elif self.options.include_browser:
                self.logger.info("Browser render skipped url=%s reason=http_html_has_enough_content", target.url)
        else:
            extracted_payload = self.extractor.extract_fetch_result(fetch_result)
            artifact["extracted"] = extracted_payload
            artifact["objective"] = self._extract_objective_from_payload(extracted_payload, source_url=fetch_result.final_url)
            queued_docs = self._queue_discoveries(extracted_payload.get("discovered_urls", []), target, frontier, "document_url")
            self.logger.info(
                "Extracted non-HTML kind=%s queued_discovered_urls=%s objective_score=%s objective_records=%s url=%s",
                extracted_payload.get("kind"),
                queued_docs,
                (artifact["objective"] or {}).get("score"),
                (artifact["objective"] or {}).get("record_count"),
                target.url,
            )

        artifact["content_fingerprint"] = self._content_fingerprint(artifact)
        return artifact

    def _fetch_with_retry(self, url: str) -> FetchResult:
        attempt = 0

        def operation() -> FetchResult:
            nonlocal attempt
            attempt += 1
            self.logger.info("HTTP attempt %s/%s url=%s", attempt, self.options.max_retries + 1, url)
            result = self.fetcher.fetch(url)
            if result.status_code in RETRYABLE_STATUS_CODES:
                self.logger.warning("Retryable HTTP status=%s url=%s", result.status_code, url)
                raise RuntimeError(f"Retryable HTTP status {result.status_code}")
            return result

        return with_retries(
            operation,
            max_retries=self.options.max_retries,
            backoff_seconds=self.options.backoff_seconds,
        )

    def _collect_browser_with_retry(self, target: CrawlTarget, frontier: CrawlFrontier) -> Dict[str, Any]:
        attempt = 0

        def operation() -> Dict[str, Any]:
            nonlocal attempt
            attempt += 1
            self.logger.info("Browser attempt %s/%s url=%s", attempt, self.options.max_retries + 1, target.url)
            try:
                return self._collect_browser(target, frontier)
            except Exception as exc:
                self.logger.warning("Browser attempt failed url=%s attempt=%s error=%s", target.url, attempt, exc)
                self._reset_browser()
                raise

        return with_retries(
            operation,
            max_retries=self.options.max_retries,
            backoff_seconds=self.options.backoff_seconds,
        )

    def _collect_browser(self, target: CrawlTarget, frontier: CrawlFrontier) -> Dict[str, Any]:
        if self.browser is None:
            self.logger.info("Starting Playwright browser headless=%s screenshot=%s", self.options.browser_headless, self.options.browser_screenshot)
            self.browser = BrowserCollector(
                user_agent=self.user_agent,
                headless=self.options.browser_headless,
                screenshot=self.options.browser_screenshot,
            )
        self.logger.info("Browser collect start url=%s", target.url)
        browser_result = self.browser.collect(target.url)
        rendered = self.extractor.extract_html(
            browser_result.rendered_html,
            browser_result.final_url,
            include_raw=self.options.save_raw_html,
        )
        queued_rendered = self._queue_discoveries(rendered.links, target, frontier, "rendered_link")
        queued_network = self._queue_discoveries(
            [call["url"] for call in browser_result.network_calls if call.get("event") == "response"],
            target,
            frontier,
            "network",
        )
        self.logger.info(
            "Browser collect done final_url=%s rendered_text_chars=%s rendered_links=%s queued_rendered=%s network_events=%s queued_network=%s cookies=%s local_storage_keys=%s session_storage_keys=%s",
            browser_result.final_url,
            len(rendered.text or ""),
            len(rendered.links),
            queued_rendered,
            len(browser_result.network_calls),
            queued_network,
            len(browser_result.cookies),
            len(browser_result.local_storage),
            len(browser_result.session_storage),
        )
        payload = asdict(browser_result)
        payload["rendered_extracted"] = asdict(rendered)
        payload["objective"] = self._extract_objective_from_page(rendered, source_url=browser_result.final_url)
        if browser_result.screenshot_bytes:
            payload["screenshot_base64"] = base64.b64encode(browser_result.screenshot_bytes).decode("ascii")
        payload.pop("screenshot_bytes", None)
        return payload

    def _reset_browser(self) -> None:
        if self.browser is None:
            return
        try:
            self.browser.close()
        except Exception:
            pass
        self.browser = None

    def _queue_optional_discoveries(self, extracted: Any, target: CrawlTarget, frontier: CrawlFrontier) -> None:
        if self.options.include_files:
            queued = self._queue_discoveries(extracted.files, target, frontier, "file")
            if extracted.files:
                self.logger.info("Queued files discovered=%s queued=%s parent=%s", len(extracted.files), queued, target.url)
        if self.options.include_feeds:
            queued = self._queue_discoveries(extracted.feeds, target, frontier, "feed")
            if extracted.feeds:
                self.logger.info("Queued feeds discovered=%s queued=%s parent=%s", len(extracted.feeds), queued, target.url)
        if self.options.include_sitemaps:
            queued = self._queue_discoveries(extracted.sitemaps, target, frontier, "sitemap")
            if extracted.sitemaps:
                self.logger.info("Queued sitemaps discovered=%s queued=%s parent=%s", len(extracted.sitemaps), queued, target.url)
        queued = self._queue_discoveries(extracted.api_candidates, target, frontier, "api_candidate")
        if extracted.api_candidates:
            self.logger.info("Queued API candidates discovered=%s queued=%s parent=%s", len(extracted.api_candidates), queued, target.url)

    def _queue_discoveries(self, urls: Iterable[str], target: CrawlTarget, frontier: CrawlFrontier, source: str) -> int:
        next_depth = target.depth + 1
        queued = 0
        for url in urls:
            if next_depth <= self.options.max_depth or looks_like_file(url) or looks_like_feed(url):
                priority = self._priority_for_url(url)
                if frontier.add(url, depth=next_depth, source=source, parent_url=target.url, priority=priority):
                    queued += 1
                    self.logger.info(
                        "Queued discovery depth=%s priority=%s source=%s url=%s parent=%s",
                        next_depth,
                        priority,
                        source,
                        url,
                        target.url,
                    )
        return queued

    def _priority_for_url(self, url: str) -> int:
        if not self.options.prioritize_objective or not self.objective_extractor:
            return 0
        return self.objective_extractor.score_url(url)

    def _extract_objective_from_page(self, extracted: Any, *, source_url: str) -> Optional[Dict[str, Any]]:
        if not self.objective_extractor:
            return None
        objective = self.objective_extractor.extract_page_records(extracted, run_id=self.run_id, source_url=source_url)
        if objective["is_relevant"]:
            self.logger.info(
                "Objective match objective=%s score=%s records=%s source_url=%s",
                objective["name"],
                objective["score"],
                objective["record_count"],
                source_url,
            )
        return objective

    def _extract_objective_from_payload(self, payload: Any, *, source_url: str) -> Optional[Dict[str, Any]]:
        if not self.objective_extractor:
            return None
        objective = self.objective_extractor.extract_payload_records(payload, run_id=self.run_id, source_url=source_url)
        if objective["is_relevant"]:
            self.logger.info(
                "Objective payload match objective=%s score=%s records=%s source_url=%s",
                objective["name"],
                objective["score"],
                objective["record_count"],
                source_url,
            )
        return objective

    def _should_render(self, extracted: Any) -> bool:
        text_len = len(extracted.text or "")
        has_app_shell = any(key in (extracted.raw_html or "") for key in ("__NEXT_DATA__", "id=\"root\"", "id=\"app\""))
        return text_len < 500 or bool(extracted.forms) or has_app_shell

    def _http_payload(self, fetch_result: FetchResult) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"body_text": fetch_result.body_text}
        if self.options.save_binary_files and fetch_result.body_bytes and fetch_result.body_text is None:
            payload["body_base64"] = base64.b64encode(fetch_result.body_bytes).decode("ascii")
            payload["body_encoding"] = "base64"
        elif fetch_result.body_bytes and fetch_result.body_text is None:
            payload["body_size_bytes"] = len(fetch_result.body_bytes)
        return payload

    def _save_artifact(self, artifact: Dict[str, Any], collection: str) -> tuple[str, bool]:
        if not self.store:
            raise RuntimeError("Mongo store is not configured.")
        inserted_id, inserted = self.store.save_artifact(artifact, collection)
        return str(inserted_id), inserted

    def _save_objective_records(self, artifact: Dict[str, Any], collection: str) -> tuple[int, int, List[Any]]:
        if not self.store or not self.objective_extractor:
            return 0, 0, []
        records: List[Dict[str, Any]] = []
        objective = artifact.get("objective") or {}
        records.extend(objective.get("standardized_records") or [])
        browser = artifact.get("browser") or {}
        browser_objective = browser.get("objective") or {}
        records.extend(browser_objective.get("standardized_records") or [])
        if not records:
            return 0, 0, []
        return self.store.save_records(records, collection)

    def _artifact_key(self, url: str, artifact_type: str) -> str:
        return f"{artifact_type}:{url}"

    def _content_fingerprint(self, artifact: Dict[str, Any]) -> str:
        comparable = {
            "artifact_type": artifact.get("artifact_type"),
            "url": artifact.get("url"),
            "final_url": artifact.get("final_url"),
            "status_code": artifact.get("status_code"),
            "content_type": artifact.get("content_type"),
            "http": artifact.get("http"),
            "browser_rendered_html": (artifact.get("browser") or {}).get("rendered_html"),
            "objective_records": (artifact.get("objective") or {}).get("standardized_records"),
        }
        raw = json.dumps(comparable, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _collection_for_url(self, base_collection: str, url: str) -> str:
        if not self.options.collection_per_domain:
            return base_collection
        parsed = urlparse(url)
        host = parsed.hostname or "unknown_site"
        slug = re.sub(r"[^a-z0-9]+", "_", host.lower()).strip("_") or "unknown_site"
        return f"{base_collection}__{slug}"

    def _record_failure(self, failure: CrawlFailure, *, save: bool) -> None:
        self.logger.warning("Smart crawler failure at %s for %s: %s", failure.stage, failure.url, failure.message)
        if save and self.store:
            collection = self._collection_for_url(self.options.failure_collection, failure.url)
            self.store.save_failure(
                {
                    "run_id": self.run_id,
                    **failure.as_dict(),
                },
                collection,
            )


def _is_html(result: FetchResult) -> bool:
    content_type = result.content_type.lower()
    if "html" in content_type:
        return True
    if not result.body_text:
        return False
    prefix = result.body_text.lstrip()[:20].lower()
    return prefix.startswith("<!") or prefix.startswith("<html")


def _is_http_error(result: FetchResult) -> bool:
    return result.status_code is not None and result.status_code >= 400
