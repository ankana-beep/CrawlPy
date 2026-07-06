# CrawlPy

Python scraping framework with HTTP + browser (Playwright/Selenium) support and optional persistence to Supabase/Postgres.

## Setup

Install Python dependencies:

```bash
pip install -r scraper_framework/requirements.txt
```

Playwright browsers (Chromium example):

```bash
python3 -m playwright install chromium
```

See `DEPENDENCIES.md` for install commands for all Playwright browsers.

## Run

Run a scrape for any URL:

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com
```

Save result to Supabase/Postgres (requires `.env` configured):

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com --save
```

Force browser rendering (Playwright/Selenium) for dynamic pages:

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com --use-browser
```
