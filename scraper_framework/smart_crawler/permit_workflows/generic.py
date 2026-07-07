"""Controlled generic permit search workflow."""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

from scraper_framework.smart_crawler.browser_collector import _capture_request, _capture_response
from scraper_framework.smart_crawler.extractors import GenericExtractor
from scraper_framework.smart_crawler.permit_objective import PermitObjectiveExtractor
from scraper_framework.smart_crawler.permit_workflows.detector import detect_portal_type
from scraper_framework.smart_crawler.permit_workflows.models import PermitWorkflowOptions, PermitWorkflowResult
from scraper_framework.smart_crawler.url_tools import normalize_url, should_skip_url


class GenericPermitWorkflow:
    """Search permit portals without site-specific destructive behavior."""

    def __init__(self, objective_extractor: PermitObjectiveExtractor, extractor: Optional[GenericExtractor] = None):
        self.objective_extractor = objective_extractor
        self.extractor = extractor or GenericExtractor()

    def run(self, url: str, *, run_id: str, options: PermitWorkflowOptions) -> PermitWorkflowResult:
        result = PermitWorkflowResult(ran=True)
        network_calls: List[Dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=options.headless)
            context_kwargs = {"user_agent": options.user_agent} if options.user_agent else {}
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.on("request", lambda request: _capture_request(network_calls, request))
            page.on("response", lambda response: _capture_response(network_calls, response))
            try:
                page.goto(url, wait_until=options.wait_until, timeout=options.timeout_ms)
                _wait_soft(page)
                html = page.content()
                extracted = self.extractor.extract_html(html, page.url, include_raw=False)
                result.portal_type = detect_portal_type(page.url, extracted)
                self._collect_records(result, extracted, run_id=run_id, source_url=page.url)
                self._collect_network_records(result, network_calls, run_id=run_id, source_url=page.url)

                if self._submit_safe_search(page, result, options):
                    _wait_soft(page)
                    html = page.content()
                    extracted = self.extractor.extract_html(html, page.url, include_raw=False)
                    self._collect_records(result, extracted, run_id=run_id, source_url=page.url)
                    self._collect_network_records(result, network_calls, run_id=run_id, source_url=page.url)

                self._crawl_pagination(page, result, run_id=run_id, options=options, network_calls=network_calls)
                detail_urls = self._detail_urls(page)
                result.detail_urls = detail_urls[: options.max_detail_pages]
                for detail_url in result.detail_urls:
                    if should_skip_url(detail_url):
                        continue
                    detail_page = context.new_page()
                    detail_network: List[Dict[str, Any]] = []
                    detail_page.on("request", lambda request: _capture_request(detail_network, request))
                    detail_page.on("response", lambda response: _capture_response(detail_network, response))
                    try:
                        detail_page.goto(detail_url, wait_until=options.wait_until, timeout=options.timeout_ms)
                        _wait_soft(detail_page)
                        detail_html = detail_page.content()
                        detail_extracted = self.extractor.extract_html(detail_html, detail_page.url, include_raw=False)
                        self._collect_records(result, detail_extracted, run_id=run_id, source_url=detail_page.url)
                        self._collect_network_records(result, detail_network, run_id=run_id, source_url=detail_page.url)
                        result.actions.append({"type": "detail_page", "url": detail_page.url})
                    except Exception as exc:
                        result.failures.append({"stage": "detail_page", "url": detail_url, "message": str(exc)})
                    finally:
                        try:
                            detail_page.close()
                        except Exception:
                            pass
            except Exception as exc:
                result.failures.append({"stage": "workflow", "url": url, "message": str(exc)})
            finally:
                context.close()
                browser.close()

        result.network_urls = _network_urls(network_calls)
        result.records = _dedupe_records(result.records)
        return result

    def _submit_safe_search(self, page: Page, result: PermitWorkflowResult, options: PermitWorkflowOptions) -> bool:
        filled = self._fill_date_fields(page, result, options.date_lookback_days)
        clicked = self._click_search(page, result)
        return filled or clicked

    def _fill_date_fields(self, page: Page, result: PermitWorkflowResult, lookback_days: int) -> bool:
        start = date.today() - timedelta(days=lookback_days)
        end = date.today()
        start_value = start.strftime("%m/%d/%Y")
        end_value = end.strftime("%m/%d/%Y")
        filled = False
        inputs = page.locator("input")
        for index in range(min(inputs.count(), 80)):
            field = inputs.nth(index)
            try:
                field_type = (field.get_attribute("type") or "").lower()
                label = _field_fingerprint(field)
                if field_type not in {"date", "text", "search", ""}:
                    continue
                if _is_end_date(label):
                    field.fill(end.isoformat() if field_type == "date" else end_value)
                    result.actions.append({"type": "fill_date", "field": label, "value": end_value})
                    filled = True
                elif _is_start_date(label):
                    field.fill(start.isoformat() if field_type == "date" else start_value)
                    result.actions.append({"type": "fill_date", "field": label, "value": start_value})
                    filled = True
            except Exception:
                continue
        return filled

    def _click_search(self, page: Page, result: PermitWorkflowResult) -> bool:
        selectors = [
            "button:has-text('Search')",
            "input[type='submit'][value*='Search' i]",
            "input[type='button'][value*='Search' i]",
            "button:has-text('Submit')",
            "input[type='submit']",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 5)
            except Exception:
                continue
            for index in range(count):
                button = locator.nth(index)
                try:
                    text = (button.inner_text(timeout=1000) or button.get_attribute("value") or "").lower()
                    if any(blocked in text for blocked in ("login", "logout", "delete", "remove", "cancel")):
                        continue
                    button.click(timeout=3000)
                    result.actions.append({"type": "click_search", "selector": selector, "text": text})
                    return True
                except Exception:
                    continue
        return False

    def _crawl_pagination(
        self,
        page: Page,
        result: PermitWorkflowResult,
        *,
        run_id: str,
        options: PermitWorkflowOptions,
        network_calls: List[Dict[str, Any]],
    ) -> None:
        for _ in range(max(0, options.max_pages - 1)):
            next_button = _first_enabled(
                page,
                [
                    "a:has-text('Next')",
                    "button:has-text('Next')",
                    "a[aria-label*='next' i]",
                    "button[aria-label*='next' i]",
                    "a:has-text('Load More')",
                    "button:has-text('Load More')",
                ],
            )
            if next_button is None:
                return
            try:
                next_button.click(timeout=3000)
                _wait_soft(page)
                html = page.content()
                extracted = self.extractor.extract_html(html, page.url, include_raw=False)
                self._collect_records(result, extracted, run_id=run_id, source_url=page.url)
                self._collect_network_records(result, network_calls, run_id=run_id, source_url=page.url)
                result.actions.append({"type": "pagination", "url": page.url})
            except Exception as exc:
                result.failures.append({"stage": "pagination", "url": page.url, "message": str(exc)})
                return

    def _detail_urls(self, page: Page) -> List[str]:
        out: List[str] = []
        anchors = page.locator("a[href]")
        for index in range(min(anchors.count(), 500)):
            try:
                href = anchors.nth(index).get_attribute("href") or ""
                url = normalize_url(urljoin(page.url, href))
                if url and _looks_like_detail_url(url):
                    out.append(url)
            except Exception:
                continue
        return _unique(out)

    def _collect_records(self, result: PermitWorkflowResult, extracted: Any, *, run_id: str, source_url: str) -> None:
        objective = self.objective_extractor.extract_page_records(extracted, run_id=run_id, source_url=source_url)
        if objective["standardized_records"]:
            result.records.extend(objective["standardized_records"])
            result.actions.append({"type": "extract_page_records", "url": source_url, "count": objective["record_count"]})

    def _collect_network_records(self, result: PermitWorkflowResult, calls: Iterable[Dict[str, Any]], *, run_id: str, source_url: str) -> None:
        for payload in _network_payloads(calls):
            objective = self.objective_extractor.extract_payload_records(payload, run_id=run_id, source_url=source_url)
            if objective["standardized_records"]:
                result.records.extend(objective["standardized_records"])
                result.actions.append({"type": "extract_network_records", "url": source_url, "count": objective["record_count"]})


def _wait_soft(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass


def _field_fingerprint(field: Any) -> str:
    values = []
    for attr in ("name", "id", "placeholder", "aria-label", "title"):
        try:
            values.append(field.get_attribute(attr) or "")
        except Exception:
            pass
    return " ".join(values).lower()


def _is_start_date(text: str) -> bool:
    return any(hint in text for hint in ("start", "from", "begin", "after", "applied", "issued")) and "date" in text


def _is_end_date(text: str) -> bool:
    return any(hint in text for hint in ("end", "to", "through", "before", "until")) and "date" in text


def _first_enabled(page: Page, selectors: List[str]) -> Any:
    for selector in selectors:
        locator = page.locator(selector)
        try:
            for index in range(min(locator.count(), 5)):
                candidate = locator.nth(index)
                if candidate.is_enabled(timeout=1000):
                    return candidate
        except Exception:
            continue
    return None


def _looks_like_detail_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in ("permit", "record", "case", "application", "detail", "capid"))


def _network_payloads(calls: Iterable[Dict[str, Any]]) -> Iterable[Any]:
    for call in calls:
        body = call.get("body_base64")
        if not body:
            continue
        try:
            decoded = base64.b64decode(body)
            text = decoded.decode("utf-8", errors="ignore")
            yield json.loads(text)
        except Exception:
            continue


def _network_urls(calls: Iterable[Dict[str, Any]]) -> List[str]:
    return _unique(call["url"] for call in calls if call.get("url"))


def _dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for record in records:
        identity = (record.get("record_key"), record.get("record_fingerprint"))
        if identity not in seen:
            seen.add(identity)
            out.append(record)
    return out


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
