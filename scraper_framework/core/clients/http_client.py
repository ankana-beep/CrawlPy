"""HTTP client implementation using curl_cffi."""

from typing import Any, Dict, Optional

from curl_cffi import requests

from .base_client import BaseClient


class HttpClient(BaseClient):
    def __init__(self, proxies: Optional[Dict[str, str]] = None, headers: Optional[Dict[str, str]] = None):
        self.proxies = proxies or {}
        self.headers = headers or {}

    def fetch(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, data: Any = None, **kwargs) -> Any:
        request_headers = {**self.headers, **(headers or {})}
        response = requests.request(method, url, headers=request_headers, data=data, proxies=self.proxies, **kwargs)
        response.raise_for_status()
        return response

    def close(self) -> None:
        return None
