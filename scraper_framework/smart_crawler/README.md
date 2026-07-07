# Smart Crawler

Permit-focused unauthenticated hybrid crawler that runs beside the existing site-specific services.

It crawls pages, files, feeds, sitemaps, rendered DOM, and APIs only to find permit records. By default, MongoDB saves standardized permit-level records only.

The standardized permit records include fields such as:

- `permit_number`
- `permit_type`
- `permit_category`
- `status`
- `application_date`
- `issued_date`
- `final_date`
- `address`
- `parcel_number`
- `contractor`
- `owner`
- `valuation`
- `square_feet`
- `description`
- `is_residential`
- `jurisdiction`
- `county`
- `state`
- `source_url`
- `record_key`
- `record_fingerprint`
- `confidence`

Run without saving:

```bash
python3 -m scraper_framework.smart_crawler.cli https://example.com --no-save --max-pages 5
```

Run and save permit records to MongoDB:

```bash
python3 -m scraper_framework.smart_crawler.cli https://example.com https://example.org --max-pages 100 --max-depth 3
```

By default, saved data is split into recognizable per-website collections, for example:

- `building_permits__example_com`
- `smart_crawl_failures__example_com`

Use one shared collection instead:

```bash
python3 -m scraper_framework.smart_crawler.cli https://example.com --single-collection
```

Permit objective mode is enabled by default. The crawler prioritizes permit-looking URLs and writes standardized records to `building_permits`.

```bash
python3 -m scraper_framework.smart_crawler.cli https://county.example.gov --max-pages 100 --permit-collection building_permits
```

Save raw/debug crawl artifacts too:

```bash
python3 -m scraper_framework.smart_crawler.cli https://county.example.gov --save-artifacts
```

When debug artifacts are saved, each artifact includes:

- `permit_collection`
- `permit_record_ids`

Those fields link the raw/debug crawl evidence back to the main permit documents.

Run from a URL list:

```bash
python3 -m scraper_framework.smart_crawler.cli --urls-file seeds.txt --max-pages 200
```

Run a URL list one website at a time:

```bash
python3 -m scraper_framework.smart_crawler.cli --urls-file seeds.txt --sequential-sites --max-pages 40 --max-depth 2
```

With `--sequential-sites`, each URL gets its own crawl run and `--max-pages` applies per website.

Use HTTP-only mode:

```bash
python3 -m scraper_framework.smart_crawler.cli https://example.com --no-browser
```

Important defaults:

- Same-domain crawling is enabled by default.
- `robots.txt` is respected by default.
- Each domain has a configurable delay, default `1.0` second.
- HTTP and browser/render failures use bounded exponential retry from `--max-retries`; after retries are exhausted, that part is skipped and the crawl continues.
- Static assets such as JS, CSS, images, fonts, and source maps are skipped before fetch because they are not permit records.
- Missing optional discovery resources such as guessed `sitemap.xml` URLs are skipped on `404`/`410` instead of treated as crawl failures.
- Large/debug artifact bodies are protected before MongoDB insert; static or oversized bodies keep URL/status/headers/content type/size/hash metadata instead of full content.
- MongoDB creates document `_id` values automatically; crawler-generated trace keys are stored separately as normal fields.
- Duplicate permit records are skipped using `record_key` + `record_fingerprint`; changed permit data is inserted as a new snapshot.
- Permit-like pages and APIs are queued before generic links when the objective layer is enabled.

Optional file extraction:

- PDF text extraction needs `pypdf`.
- Excel extraction needs `openpyxl`.
- Without those libraries, the crawler still stores file metadata and size.
