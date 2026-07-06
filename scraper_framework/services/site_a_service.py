"""Site A scraper with API reverse-engineering logic."""

from typing import Any, Dict, Optional

from scraper_framework.core.clients.http_client import HttpClient
from scraper_framework.core.parsers.json_parser import JSONParser
from scraper_framework.services.base_service import BaseService


class SiteAService(BaseService):
    def __init__(self, client: Optional[HttpClient] = None, parser: Optional[JSONParser] = None):
        self.client = client or HttpClient()
        self.parser = parser or JSONParser()

    def run(self, target: str, **kwargs) -> Dict[str, Any]:
        response = self.client.fetch(target, headers=kwargs.get("headers"))
        parsed = self.parser.parse(response.text)
        return {
            "target": target,
            "result": parsed,
        }
