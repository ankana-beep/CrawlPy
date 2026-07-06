# CrawlPy

Python scraping framework with HTTP + browser (Playwright/Selenium) support and optional persistence to Supabase/Postgres.

## Setup

Install Python dependencies:

```bash
pip install -r scraper_framework/requirements.txt
```

Configure environment:

- Copy `scraper_framework/.env.example` to `scraper_framework/.env` and fill in values.

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

Save result to Supabase (requires `.env` configured):

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com --save
```

Force browser rendering (Playwright/Selenium) for dynamic pages:

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com --use-browser
```

If a page times out, increase the navigation timeout or change the wait mode:

```bash
python3 -m scraper_framework.main --site site_b --target https://example.com --use-browser --timeout-ms 90000 --wait-until load
```

## Supabase

Env vars used by `--save`:

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<anon-or-service-role-key>
SUPABASE_TABLE=crawl
SUPABASE_TEXT_COLUMN=text
SUPABASE_JSON_COLUMN=json_data
```
