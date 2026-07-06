"""Site B scraper with fallback from HTTP to Playwright."""

from typing import Any, Dict, Optional

from scraper_framework.core.clients.http_client import HttpClient
from scraper_framework.core.clients.playwright_client import PlaywrightClient
from scraper_framework.core.parsers.bs4_parser import BS4Parser
from scraper_framework.services.base_service import BaseService


class SiteBService(BaseService):
    def __init__(self, http_client: Optional[HttpClient] = None, browser_client: Optional[PlaywrightClient] = None, parser: Optional[BS4Parser] = None):
        self.http_client = http_client or HttpClient()
        self.browser_client = browser_client or PlaywrightClient()
        self.parser = parser or BS4Parser()

    def run(self, target: str, use_browser: bool = False, **kwargs) -> Dict[str, Any]:
        if use_browser:
            content = self.browser_client.fetch(target)
        else:
            try:
                response = self.http_client.fetch(target, headers=kwargs.get("headers"))
                content = response.text
            except Exception:
                content = self.browser_client.fetch(target)

        parsed = self.parser.parse(content)
        return {
            "target": target,
            "result": parsed,
        }
