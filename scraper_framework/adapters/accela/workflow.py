from __future__ import annotations

from datetime import datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .constants import SEARCH_WINDOW_YEARS, SELECTOR_PRIORITIES


class AccelaPlaywrightWorkflow:
    # Example test runs:
    # python3 scraper_framework/main.py --headed --limit 1
    # python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY
    # python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY --module Building

    permit_type_selector = "#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType"
    start_date_selector = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate"
    end_date_selector = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate"
    search_button_selector = "#ctl00_PlaceHolderMain_btnNewSearch"
    results_page_element_indicator = ".ACA_GridView, #ctl00_PlaceHolderMain_DataGrid"

    def __init__(self, request_timeout_ms: int) -> None:
        self.request_timeout_ms = request_timeout_ms
        self.result_pages_html: list[str] = []

    def run(self, page: Any, url: str) -> str:
        self.result_pages_html = []
        self.before_navigation(page, url)
        page.goto(url, wait_until="networkidle", timeout=self.request_timeout_ms)
        self.after_navigation(page, url)
        self.apply_site_logic(page, url)
        self.before_html_capture(page, url)
        if self.result_pages_html:
            return "\n".join(self.result_pages_html)
        return page.content()

    def before_navigation(self, page: Any, url: str) -> None:
        """Hook before opening the target URL."""

    def after_navigation(self, page: Any, url: str) -> None:
        """Hook immediately after the initial page load finishes."""

    def apply_site_logic(self, page: Any, url: str) -> None:
        selector_options = self.get_priority_options(page)
        print(f"Found selector priority options: {selector_options}")

        for option_text in selector_options:
            print(f"Selecting option in new tab: {option_text}")
            tab_page = self.open_residential_option_tab(page, url, option_text)
            self.after_residential_selection(tab_page, url, option_text)

    def get_priority_options(self, page: Any) -> list[str]:
        page.wait_for_load_state("networkidle")
        dropdown = page.locator(self.permit_type_selector)
        all_options = dropdown.locator("option").all_inner_texts()
        available_options = {option.strip(): option.strip() for option in all_options if option.strip()}
        matched_options = [
            option_text
            for option_text in SELECTOR_PRIORITIES
            if option_text in available_options
        ]
        if not matched_options:
            print(f"Dropdown options found on page: {sorted(available_options)}")
        return matched_options

    def open_residential_option_tab(self, page: Any, url: str, option_text: str) -> Any:
        tab_page = page.context.new_page()
        tab_page.goto(url, wait_until="networkidle", timeout=self.request_timeout_ms)
        tab_page.wait_for_load_state("networkidle")

        dropdown = tab_page.locator(self.permit_type_selector)
        dropdown.select_option(label=option_text)
        tab_page.wait_for_load_state("networkidle")
        self.apply_date_range(tab_page)
        return tab_page

    def after_residential_selection(self, page: Any, url: str, option_text: str) -> None:
        self.click_search(page)
        self.result_pages_html.append(page.content())
        # Write the next step for each selected option here.
        # Example steps:
        # - verify the selected value stayed selected after postback
        # - wait for the result grid
        # - scrape rows or detail links
        # - paginate
        # - save/export data
        pass

    def before_html_capture(self, page: Any, url: str) -> None:
        """Hook for final waits or UI cleanup before we capture page HTML."""

    def apply_date_range(self, page: Any) -> None:
        page.wait_for_load_state("networkidle")

        today = datetime.now()
        start_date = today - relativedelta(years=SEARCH_WINDOW_YEARS)

        current_date_str = today.strftime("%m/%d/%Y")
        start_date_str = start_date.strftime("%m/%d/%Y")
        print(f"Setting date range from: {start_date_str} to: {current_date_str}")

        start_date_input = page.locator(self.start_date_selector)
        start_date_input.fill("")
        start_date_input.type(start_date_str)

        end_date_input = page.locator(self.end_date_selector)
        end_date_input.fill("")
        end_date_input.type(current_date_str)
        end_date_input.press("Tab")

    def click_search(self, page: Any) -> None:
        print("Attempting to click search and wait for results...")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(self.search_button_selector).click()
        except PlaywrightTimeoutError:
            print("Primary networkidle navigation timed out. Attempting fallback strategy...")

            page.locator(self.search_button_selector).click(force=True)
            page.wait_for_load_state("networkidle", timeout=20000)

            try:
                page.wait_for_selector(self.results_page_element_indicator, timeout=10000)
            except PlaywrightTimeoutError:
                print("Fallback failed: Results element did not appear. Page might be stuck.")
                raise

        self.print_search_result_snapshot(page)

    def print_search_result_snapshot(self, page: Any) -> None:
        title = page.title()
        current_url = page.url
        body_text = page.locator("body").inner_text().strip()
        body_preview = body_text[:1000]

        print(f"Search result URL: {current_url}")
        print(f"Search result title: {title}")
        print(f"Search result preview:\n{body_preview}")

# python3 scraper_framework/main.py --headed --limit 1
# python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY
# python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY --module Building
