"""CLI for the generic smart crawler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from scraper_framework.smart_crawler.crawler import SmartCrawler
from scraper_framework.smart_crawler.models import CrawlOptions


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid unauthenticated smart crawler")
    parser.add_argument("urls", nargs="*", help="Seed URLs to crawl")
    parser.add_argument("--urls-file", help="Text file with one seed URL per line")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--collection", default="permit_crawl_artifacts", help="Optional debug artifact collection base")
    parser.add_argument("--failure-collection", default="smart_crawl_failures")
    parser.add_argument("--no-save", action="store_true", help="Run without writing to MongoDB")
    parser.add_argument("--no-browser", action="store_true", help="Disable Playwright rendered DOM and network capture")
    parser.add_argument("--allow-cross-domain", action="store_true", help="Allow discovered links outside seed domains")
    parser.add_argument("--ignore-robots", action="store_true", help="Bypass robots.txt checks; use only when you have permission")
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--save-binary-files", action="store_true")
    parser.add_argument("--browser-screenshot", action="store_true")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument(
        "--objective",
        choices=["building_permits", "residential_building_permits", "none"],
        default="building_permits",
        help="Permit extraction objective to run before general discovery",
    )
    parser.add_argument("--no-prioritize-objective", action="store_true", help="Do not prioritize objective-looking URLs")
    parser.add_argument("--permit-collection", default="building_permits", help="MongoDB collection for standardized permit records")
    parser.add_argument("--single-collection", action="store_true", help="Do not suffix collection names by website domain")
    parser.add_argument("--save-artifacts", action="store_true", help="Also save debug crawl artifacts; default saves only permit records")
    parser.add_argument(
        "--sequential-sites",
        action="store_true",
        help="Crawl each seed URL as a separate run; max-pages applies to each site",
    )
    parser.add_argument("--no-workflows", action="store_true", help="Disable intelligent permit search/form workflows")
    parser.add_argument("--workflow-date-lookback-days", type=int, default=365, help="Date range lookback used by permit search workflows")
    parser.add_argument("--workflow-max-detail-pages", type=int, default=25, help="Maximum permit detail pages opened per workflow page")
    parser.add_argument("--workflow-max-pages", type=int, default=5, help="Maximum paginated result pages clicked per workflow page")
    args = parser.parse_args()

    urls = _collect_urls(args.urls, args.urls_file)
    if not urls:
        raise SystemExit("Provide at least one URL or --urls-file.")

    if args.sequential_sites:
        result = _crawl_sequential(urls, args)
    else:
        result = SmartCrawler(_build_options(args)).crawl(urls, save=not args.no_save)
    print(json.dumps(result, indent=2, default=str))


def _build_options(args: argparse.Namespace) -> CrawlOptions:
    return CrawlOptions(
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        same_domain_only=not args.allow_cross_domain,
        include_browser=not args.no_browser,
        respect_robots_txt=not args.ignore_robots,
        request_timeout_seconds=args.timeout_seconds,
        delay_seconds=args.delay_seconds,
        max_retries=args.max_retries,
        collection=args.collection,
        failure_collection=args.failure_collection,
        save_binary_files=args.save_binary_files,
        browser_screenshot=args.browser_screenshot,
        browser_headless=not args.headed,
        objective="" if args.objective == "none" else args.objective,
        prioritize_objective=not args.no_prioritize_objective,
        permit_collection=args.permit_collection,
        collection_per_domain=not args.single_collection,
        save_crawl_artifacts=args.save_artifacts,
        enable_permit_workflows=not args.no_workflows,
        workflow_date_lookback_days=args.workflow_date_lookback_days,
        workflow_max_detail_pages=args.workflow_max_detail_pages,
        workflow_max_pages=args.workflow_max_pages,
    )


def _crawl_sequential(urls: List[str], args: argparse.Namespace) -> Dict[str, Any]:
    site_results = []
    totals = {
        "queued": 0,
        "visited": 0,
        "saved": 0,
        "failed": 0,
        "skipped": 0,
        "duplicates": 0,
        "permit_records_saved": 0,
        "permit_records_duplicate": 0,
    }
    collections = set()
    permit_collections = set()

    for index, url in enumerate(urls, start=1):
        options = _build_options(args)
        result = SmartCrawler(options).crawl([url], save=not args.no_save)
        site_result = {
            "index": index,
            "seed_url": url,
            **result,
        }
        site_results.append(site_result)

        stats = result.get("stats", {})
        for key in ("queued", "visited", "saved", "failed", "skipped", "duplicates"):
            totals[key] += int(stats.get(key, 0))
        totals["permit_records_saved"] += int(result.get("permit_records_saved", 0))
        totals["permit_records_duplicate"] += int(result.get("permit_records_duplicate", 0))
        collections.update(result.get("collections", []))
        permit_collections.update(result.get("permit_collections", []))

    return {
        "mode": "sequential_sites",
        "site_count": len(urls),
        "max_pages_per_site": args.max_pages,
        "totals": totals,
        "collections": sorted(collections),
        "permit_collections": sorted(permit_collections),
        "sites": site_results,
    }


def _collect_urls(cli_urls: List[str], urls_file: str | None) -> List[str]:
    urls = list(cli_urls)
    if urls_file:
        urls.extend(
            line.strip()
            for line in Path(urls_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return urls


if __name__ == "__main__":
    main()
