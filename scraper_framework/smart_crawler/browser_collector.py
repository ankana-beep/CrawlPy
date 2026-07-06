"""Playwright-powered rendered DOM, network, and storage collector."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from scraper_framework.config.settings import settings
from scraper_framework.smart_crawler.models import BrowserResult


class BrowserCollector:
    def __init__(self, *, user_agent: str, headless: bool = True, screenshot: bool = False):
        self.user_agent = user_agent
        self.headless = headless
        self.screenshot = screenshot
        self.playwright = sync_playwright().start()
        self.browser: Browser = self.playwright.chromium.launch(headless=headless)
        self.context: BrowserContext = self.browser.new_context(user_agent=user_agent)

    def collect(self, url: str, *, timeout_ms: Optional[int] = None, wait_until: Optional[str] = None) -> BrowserResult:
        page = self.context.new_page()
        network_calls: List[Dict[str, Any]] = []
        console_messages: List[Dict[str, Any]] = []

        page.on("console", lambda message: console_messages.append({"type": message.type, "text": message.text}))
        page.on("request", lambda request: _capture_request(network_calls, request))
        page.on("response", lambda response: _capture_response(network_calls, response))

        timeout = int(timeout_ms or settings.playwright_timeout_ms)
        wait_mode = wait_until or settings.playwright_wait_until
        page.goto(url, wait_until=wait_mode, timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        rendered_html = page.content()
        title = page.title()
        text = page.locator("body").inner_text(timeout=5000) if page.locator("body").count() else ""
        local_storage = _storage_snapshot(page, "localStorage")
        session_storage = _storage_snapshot(page, "sessionStorage")
        cookies = self.context.cookies()
        screenshot_bytes = page.screenshot(full_page=True) if self.screenshot else None
        final_url = page.url
        page.close()

        return BrowserResult(
            final_url=final_url,
            rendered_html=rendered_html,
            text=text,
            title=title,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            network_calls=network_calls,
            console_messages=console_messages,
            screenshot_bytes=screenshot_bytes,
        )

    def close(self) -> None:
        self.context.close()
        self.browser.close()
        self.playwright.stop()


def _capture_request(network_calls: List[Dict[str, Any]], request: Any) -> None:
    post_data = request.post_data
    network_calls.append(
        {
            "event": "request",
            "url": request.url,
            "method": request.method,
            "resource_type": request.resource_type,
            "headers": dict(request.headers),
            "post_data": post_data[:10000] if post_data else None,
        }
    )


def _capture_response(network_calls: List[Dict[str, Any]], response: Any) -> None:
    entry = {
        "event": "response",
        "url": response.url,
        "status": response.status,
        "headers": dict(response.headers),
        "resource_type": response.request.resource_type,
    }
    content_type = response.headers.get("content-type", "")
    if _should_capture_body(content_type):
        try:
            body = response.body()
            if len(body) <= 500_000:
                entry["body_base64"] = base64.b64encode(body).decode("ascii")
                entry["body_encoding"] = "base64"
        except Exception as exc:
            entry["body_error"] = str(exc)
    network_calls.append(entry)


def _storage_snapshot(page: Page, storage_name: str) -> Dict[str, str]:
    script = """
        (storageName) => {
            const storage = window[storageName];
            const out = {};
            for (let i = 0; i < storage.length; i++) {
                const key = storage.key(i);
                out[key] = storage.getItem(key);
            }
            return out;
        }
    """
    try:
        return page.evaluate(script, storage_name)
    except Exception:
        return {}


def _should_capture_body(content_type: str) -> bool:
    lowered = content_type.lower()
    return "json" in lowered or "xml" in lowered or lowered.startswith("text/")
