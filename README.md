# CrawlPy

Python scraping framework with HTTP + browser (Playwright/Selenium) support and MongoDB (primary) persistence.

## Setup

Install Python dependencies:

```bash
pip install -r scraper_framework/requirements.txt
```

Configure environment:

- Copy `scraper_framework/.env.example` to `scraper_framework/.env` and fill in values.
- Add one user agent per line in `scraper_framework/config/user_agents_pool.txt`. Each scrape run will pick one entry randomly. If the file is empty or missing, CrawlPy falls back to a built-in desktop Chrome user agent.

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

Save raw scrape to MongoDB (requires `.env` configured):

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

## MongoDB

`--save` writes the raw scrape JSON into MongoDB collection `scrapes` in `MONGODB_DB`.

```bash
MONGODB_SRV=true
MONGODB_HOST=<cluster-host>
MONGODB_USERNAME=<username>
MONGODB_PASSWORD=<password>
MONGODB_DB=crawlpy
MONGODB_PARAMS=appName=CrawlPy
```

## Supabase

Supabase is intended as a secondary store. A separate script can push selected fields from MongoDB into Supabase tables.

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<anon-or-service-role-key>
SUPABASE_TABLE=crawl
SUPABASE_TEXT_COLUMN=text
SUPABASE_JSON_COLUMN=json_data
```
