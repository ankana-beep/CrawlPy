"""Selenium browser client using undetected_chromedriver."""

from typing import Any, Dict, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
import undetected_chromedriver as uc

from .base_client import BaseClient


class SeleniumClient(BaseClient):
    def __init__(self, profile_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None):
        chrome_options = uc.ChromeOptions()
        if profile_path:
            chrome_options.add_argument(f"--user-data-dir={profile_path}")
        if options:
            for option in options.get("args", []):
                chrome_options.add_argument(option)
        self.driver: WebDriver = uc.Chrome(options=chrome_options)

    def fetch(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, data: Any = None, **kwargs) -> str:
        self.driver.get(url)
        return self.driver.page_source

    def close(self) -> None:
        self.driver.quit()
