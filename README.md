# Universal Permit Crawler (Lean Refactor)

This project is a simplified adapter-based permit crawler.

It supports two URL input modes and uses one shared pipeline:

1. Get URLs
2. Detect platform adapter
3. Scrape permit data
4. Normalize to a canonical schema
5. Store in MongoDB
6. Continue to next URL even if one fails

A generic adapter is always used as fallback when no specific platform matches.

## What Was Simplified

This refactor intentionally avoids future-extensibility scaffolding (no Playwright fallback orchestration, distributed workers, scheduler, etc.).

The code keeps only practical components needed for current crawling and MongoDB storage.

## Project Structure

- `scraper_framework/main.py`: CLI entry point and crawl loop
- `scraper_framework/adapters/base/`: shared base adapter + exceptions
- `scraper_framework/adapters/accela/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/mygovernmentonline/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/tyler_energov/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/opengov/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/arcgis/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/civicplus/`: adapter, parser, extractor, detector, constants
- `scraper_framework/adapters/generic/`: fallback adapter, parser, extractor, detector
- `scraper_framework/db/mongo_client.py`: MongoDB persistence
- `scraper_framework/config/settings.py`: environment-driven settings
- `scraper_framework/urls.txt`: default URL list (one URL per line)

## Setup

```bash
cd CrawlPy
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Update `scraper_framework/.env` with MongoDB values.

## Run

### Mode 1: Single or repeated `--url`

```bash
python scraper_framework/main.py --url https://permits.city.gov/CitizenAccess/
python scraper_framework/main.py --url https://a.example --url https://b.example
```

### Mode 2: URLs from file

```bash
python scraper_framework/main.py --urls scraper_framework/urls.txt
```

If `--url` is not provided, the crawler reads from `--urls` (default: `urls.txt` in current working directory).

## MongoDB Collections

- `sources`
- `crawl_runs`
- `crawl_logs`
- `permits`

Each permit document stores:

- `source_url`
- `adapter_name`
- `crawl_timestamp`
- `normalized_data`
- `raw_data`
- `crawl_status`

## Canonical Normalized Schema

- `record_number`
- `status`
- `address`
- `record_type`
- `description`
- `issue_date`
- `applicant`
- `contractor`
- `owner`
- `parcel`
- `valuation`

