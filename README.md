# Permit Portal Scraper Automation

An automation and scraping project built with Playwright to work reliably against ASP.NET-style municipal permit portals such as Accela.

## The Problem

The target permit form uses an ASP.NET `<select>` with an inline `onchange` postback:

```html
onchange="var p = new ProcessLoading(); p.showLoading(); __doPostBack(...)"
```

That means a simple dropdown selection is not enough. As soon as one option is chosen, the page can reload, rerender controls, and lose state if the script moves too fast.

## Current Accela Flow

The current Playwright workflow lives in [workflow.py](/home/sourabh/CrawlPy/scraper_framework/adapters/accela/workflow.py) and behaves like this:

1. Open the target Accela URL in Playwright.
2. Wait for `networkidle`.
3. Read all options from `#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType`.
4. Keep only the exact labels listed in `SELECTOR_PRIORITIES`.
5. For each matching label, open a new browser tab.
6. In that new tab, reopen the same URL.
7. Select the permit type with `select_option(label=...)`.
8. Wait again for the ASP.NET postback to finish.
9. Apply the dynamic date range.
10. Hand off to `after_residential_selection(...)` for the next search/scrape logic.

## Constants That Drive The Flow

These values live in [constants.py](/home/sourabh/CrawlPy/scraper_framework/adapters/accela/constants.py):

- `URLS`: agency and module URLs
- `SELECTOR_PRIORITIES`: exact permit-type labels to search
- `SEARCH_WINDOW_YEARS`: current lookback window for the date filter

## Date Behavior

For every selected permit type tab, the workflow sets:

- start date = today minus `SEARCH_WINDOW_YEARS`
- end date = today

These values are filled into:

- `#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate`
- `#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate`

Then the script tabs out so the portal registers the date change.

## Where To Add More Logic

Write the next site-specific steps in:

- [workflow.py](/home/sourabh/CrawlPy/scraper_framework/adapters/accela/workflow.py) -> `after_residential_selection(...)`

That is the right place to add:

- verify sticky selection
- click Search
- wait for result grid
- paginate
- scrape rows or detail pages
- save/export data

## Test Commands

Run one URL only:

```bash
python3 scraper_framework/main.py --headed --limit 1
```

Run one agency only:

```bash
python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY
```

Run one agency/module only:

```bash
python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY --module Building
```

Run all resolved URLs headless:

```bash
python3 scraper_framework/main.py
```

## Setup

```bash
cd CrawlPy
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
```

Update `scraper_framework/.env` with MongoDB values before full runs.
