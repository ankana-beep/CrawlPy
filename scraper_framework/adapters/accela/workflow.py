from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .constants import (
    BROWSER_NAVIGATION_TIMEOUT_MS,
    BROWSER_POSTBACK_TIMEOUT_MS,
    BROWSER_RESULTS_TIMEOUT_MS,
    MAX_CONCURRENT_PAGES,
    SEARCH_WINDOW_YEARS,
    SELECTOR_PRIORITIES,
    WORKER_PAGE_NAVIGATION_RETRIES,
)


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
    pagination_link_selector = ".aca_pagination td.aca_pagination_td a"
    pagination_cell_selector = ".aca_pagination td.aca_pagination_td"
    pagination_more_text = "..."
    pagination_next_text = "Next"

    def __init__(self, request_timeout_ms: int) -> None:
        self.request_timeout_ms = request_timeout_ms
        self.result_pages_html: list[str] = []
        self.page_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

    async def run(self, page: Any, url: str) -> str:
        self.result_pages_html = []
        await self.before_navigation(page, url)
        await self.goto_search_page(page, url)
        await self.after_navigation(page, url)
        await self.apply_site_logic(page, url)
        await self.before_html_capture(page, url)
        if self.result_pages_html:
            return "\n".join(self.result_pages_html)
        return await page.content()

    async def before_navigation(self, page: Any, url: str) -> None:
        """Hook before opening the target URL."""

    async def after_navigation(self, page: Any, url: str) -> None:
        """Hook immediately after the initial page load finishes."""

    async def apply_site_logic(self, page: Any, url: str) -> None:
        selector_options = await self.get_priority_options(page)
        print(f"Found selector priority options: {selector_options}")

        for option_text in selector_options:
            print(f"Selecting option in new tab: {option_text}")
            tab_page = await self.open_residential_option_tab(page, url, option_text)
            try:
                await self.after_residential_selection(tab_page, url, option_text)
            finally:
                await tab_page.close()

    async def get_priority_options(self, page: Any) -> list[str]:
        await page.wait_for_load_state("networkidle")
        dropdown = page.locator(self.permit_type_selector)
        all_options = await dropdown.locator("option").all_inner_texts()
        available_options = {option.strip(): option.strip() for option in all_options if option.strip()}
        matched_options = [
            option_text
            for option_text in SELECTOR_PRIORITIES
            if option_text in available_options
        ]
        if not matched_options:
            print(f"Dropdown options found on page: {sorted(available_options)}")
        return matched_options

    async def open_residential_option_tab(self, page: Any, url: str, option_text: str) -> Any:
        tab_page = await page.context.new_page()
        await self.goto_search_page(tab_page, url)

        dropdown = tab_page.locator(self.permit_type_selector)
        await dropdown.select_option(label=option_text)
        await self.wait_for_postback_settle(tab_page, self.permit_type_selector)
        await self.apply_date_range(tab_page)
        return tab_page

    async def after_residential_selection(self, page: Any, url: str, option_text: str) -> None:
        await self.click_search(page)
        await self.collect_paginated_results(page, url, option_text)
        # Write the next step for each selected option here.
        # Example steps:
        # - verify the selected value stayed selected after postback
        # - wait for the result grid
        # - scrape rows or detail links
        # - paginate
        # - save/export data

    async def before_html_capture(self, page: Any, url: str) -> None:
        """Hook for final waits or UI cleanup before we capture page HTML."""

    async def apply_date_range(self, page: Any) -> None:
        await page.wait_for_load_state("networkidle")

        today = datetime.now()
        start_date = today - relativedelta(years=SEARCH_WINDOW_YEARS)

        current_date_str = today.strftime("%m/%d/%Y")
        start_date_str = start_date.strftime("%m/%d/%Y")
        print(f"Setting date range from: {start_date_str} to: {current_date_str}")

        start_date_input = page.locator(self.start_date_selector)
        await start_date_input.fill("")
        await start_date_input.type(start_date_str)

        end_date_input = page.locator(self.end_date_selector)
        await end_date_input.fill("")
        await end_date_input.type(current_date_str)
        await end_date_input.press("Tab")

    async def click_search(self, page: Any) -> None:
        print("Attempting to click search and wait for results...")

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            ):
                await page.locator(self.search_button_selector).click()
        except PlaywrightTimeoutError:
            print("Primary navigation timed out. Attempting fallback strategy...")

            await page.locator(self.search_button_selector).click(force=True)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            )

            try:
                await page.wait_for_selector(
                    self.results_page_element_indicator,
                    timeout=BROWSER_RESULTS_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                print("Fallback failed: Results element did not appear. Page might be stuck.")
                raise
        else:
            await page.wait_for_selector(
                self.results_page_element_indicator,
                timeout=BROWSER_RESULTS_TIMEOUT_MS,
            )

        await self.print_search_result_snapshot(page)

    async def print_search_result_snapshot(self, page: Any) -> None:
        title = await page.title()
        current_url = page.url
        body_text = (await page.locator("body").inner_text()).strip()
        body_preview = body_text[:1000]

        print(f"Search result URL: {current_url}")
        print(f"Search result title: {title}")
        print(f"Search result preview:\n{body_preview}")

    async def collect_paginated_results(self, page: Any, url: str, option_text: str) -> None:
        await self.wait_for_results_page(page)
        self.result_pages_html.append(await page.content())

        processed_pages = {1}

        while True:
            batch_pages = await self.get_visible_page_numbers(page, processed_pages)
            if not batch_pages:
                if not await self.advance_pagination_window(page, processed_pages):
                    break
                batch_pages = await self.get_visible_page_numbers(page, processed_pages)
                if not batch_pages:
                    break

            print(f"Processing page batch {batch_pages[0]} to {batch_pages[-1]} concurrently...")
            print(f"Using up to {MAX_CONCURRENT_PAGES} concurrent page workers...")
            processed_pages.update(batch_pages)
            tasks = [
                self.fetch_target_results_page(page.context, url, option_text, page_num)
                for page_num in batch_pages
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for page_num, batch_result in zip(batch_pages, batch_results, strict=False):
                if isinstance(batch_result, Exception):
                    print(f"Failed to fetch Page {page_num}: {batch_result}")
                    continue
                if batch_result:
                    self.result_pages_html.append(batch_result)

            if not await self.advance_pagination_window(page, processed_pages):
                break

    async def get_visible_page_numbers(self, page: Any, processed_pages: set[int]) -> list[int]:
        page_links = page.locator(self.pagination_link_selector)
        visible_pages: list[int] = []

        for index in range(await page_links.count()):
            link_text = (await page_links.nth(index).inner_text()).strip()
            if link_text.isdigit():
                page_num = int(link_text)
                if page_num not in processed_pages:
                    visible_pages.append(page_num)

        return sorted(set(visible_pages))

    async def advance_pagination_window(self, page: Any, processed_pages: set[int]) -> bool:
        current_max_processed = max(processed_pages)
        if await self.click_page_number_if_visible(page, current_max_processed):
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        if await self.click_special_pagination_control(page, self.pagination_more_text):
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        pagination_cells = page.locator(self.pagination_cell_selector)
        for index in range(await pagination_cells.count()):
            cell = pagination_cells.nth(index)
            cell_text = (await cell.inner_text()).strip()
            if self.pagination_next_text not in cell_text:
                continue

            next_link = cell.locator("a")
            if await next_link.count() == 0 or not await next_link.first.is_visible():
                continue

            await self.click_and_wait_for_results(page, next_link.first)
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        return False

    async def click_page_number_if_visible(self, page: Any, target_page_num: int) -> bool:
        page_links = page.locator(self.pagination_link_selector)
        for index in range(await page_links.count()):
            link = page_links.nth(index)
            link_text = (await link.inner_text()).strip()
            if link_text == str(target_page_num) and await link.is_visible():
                await self.click_and_wait_for_results(page, link)
                return True
        return False

    async def fetch_target_results_page(
        self,
        context: Any,
        url: str,
        option_text: str,
        target_page_num: int,
    ) -> str | None:
        async with self.page_semaphore:
            last_error: Exception | None = None
            for attempt in range(1, WORKER_PAGE_NAVIGATION_RETRIES + 1):
                worker_page = await context.new_page()
                try:
                    print(f"Opening worker for Page {target_page_num} (attempt {attempt})...")
                    await self.goto_search_page(worker_page, url)

                    dropdown = worker_page.locator(self.permit_type_selector)
                    await dropdown.select_option(label=option_text)
                    await self.wait_for_postback_settle(worker_page, self.permit_type_selector)
                    await self.apply_date_range(worker_page)
                    await self.click_search(worker_page)

                    if target_page_num > 1 and not await self.go_to_results_page(worker_page, target_page_num):
                        print(f"Could not reach Page {target_page_num}.")
                        return None

                    return await worker_page.content()
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                    print(
                        f"Worker timeout on Page {target_page_num} attempt {attempt}. Retrying..."
                    )
                finally:
                    await worker_page.close()

            if last_error is not None:
                raise last_error
            return None

    async def go_to_results_page(self, page: Any, current_page_num: int) -> bool:
        while True:
            page_links = page.locator(self.pagination_link_selector)
            for index in range(await page_links.count()):
                link = page_links.nth(index)
                link_text = (await link.inner_text()).strip()
                if link_text == str(current_page_num) and await link.is_visible():
                    await self.click_and_wait_for_results(page, link)
                    return True

            if not await self.advance_results_window_once(page):
                return False

    async def advance_results_window_once(self, page: Any) -> bool:
        if await self.click_special_pagination_control(page, self.pagination_more_text):
            return True

        pagination_cells = page.locator(self.pagination_cell_selector)
        for index in range(await pagination_cells.count()):
            cell = pagination_cells.nth(index)
            cell_text = (await cell.inner_text()).strip()
            if self.pagination_next_text not in cell_text:
                continue

            next_link = cell.locator("a")
            if await next_link.count() == 0 or not await next_link.first.is_visible():
                continue

            await self.click_and_wait_for_results(page, next_link.first)
            return True

        return False

    async def click_special_pagination_control(self, page: Any, control_text: str) -> bool:
        page_links = page.locator(self.pagination_link_selector)
        for index in range(await page_links.count()):
            link = page_links.nth(index)
            link_text = (await link.inner_text()).strip()
            if link_text == control_text and await link.is_visible():
                await self.click_and_wait_for_results(page, link)
                return True
        return False

    async def click_and_wait_for_results(self, page: Any, locator: Any) -> None:
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            ):
                await locator.click()
        except PlaywrightTimeoutError:
            await locator.click(force=True)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            )

        await self.wait_for_results_page(page)

    async def goto_search_page(self, page: Any, url: str) -> None:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
        )
        await page.wait_for_selector(
            self.permit_type_selector,
            timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
        )

    async def wait_for_postback_settle(self, page: Any, selector: str) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_selector(selector, timeout=BROWSER_POSTBACK_TIMEOUT_MS)

    async def wait_for_results_page(self, page: Any) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_selector(
            self.results_page_element_indicator,
            timeout=BROWSER_RESULTS_TIMEOUT_MS,
        )
