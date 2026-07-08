from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from adapters.accela.constants import URLS as ACCELA_URLS
from adapters.accela.adapter import AccelaAdapter
from adapters.base.base_adapter import BaseAdapter
from adapters.detector import AdapterDetector, build_adapters
from db.mongo_client import MongoStore
from utils.logger import get_logger

logger = get_logger("crawler")


def load_urls_from_file(file_path: str | Path) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"URL file not found: {path}")

    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


def load_accela_urls(agencies: Iterable[str] | None = None, modules: Iterable[str] | None = None) -> list[str]:
    agency_filter = {value.strip().upper() for value in (agencies or []) if value.strip()}
    module_filter = {value.strip().lower() for value in (modules or []) if value.strip()}
    selected_urls: list[str] = []

    for agency_key, agency_config in ACCELA_URLS.items():
        if agency_filter and agency_key.upper() not in agency_filter:
            continue

        target_scrape_urls = agency_config.get("target_scrape_urls", {})
        ordered_modules = agency_config.get("modules", list(target_scrape_urls.keys()))
        for module_name in ordered_modules:
            if module_filter and module_name.lower() not in module_filter:
                continue

            url = target_scrape_urls.get(module_name)
            if url:
                selected_urls.append(url)

    return selected_urls


def get_source_metadata(source_url: str) -> dict[str, str | None]:
    for agency_key, agency_config in ACCELA_URLS.items():
        target_scrape_urls = agency_config.get("target_scrape_urls", {})
        for module_name, configured_url in target_scrape_urls.items():
            if configured_url == source_url:
                return {
                    "agency_key": agency_key,
                    "county_name": agency_config.get("agency_name"),
                    "module_name": module_name,
                }

    return {
        "agency_key": None,
        "county_name": None,
        "module_name": None,
    }


def limit_urls(urls: list[str], limit: int | None = None) -> list[str]:
    if limit is None or limit <= 0:
        return urls
    return urls[:limit]


def crawl(urls: Iterable[str], headed: bool = False) -> None:
    adapters: list[BaseAdapter] = build_adapters()
    accela_adapter = next((adapter for adapter in adapters if isinstance(adapter, AccelaAdapter)), None)
    for adapter in adapters:
        if isinstance(adapter, AccelaAdapter):
            adapter.headed = headed
    detector = AdapterDetector(adapters)
    store = MongoStore()

    for source_url in urls:
        source_url = source_url.strip()
        if not source_url:
            continue

        run_id = None
        source_metadata = get_source_metadata(source_url)
        logger.info("Crawling %s", source_url)

        try:
            bootstrap_adapter = accela_adapter if "accela" in source_url.lower() and accela_adapter else adapters[0]
            html = bootstrap_adapter.fetch_html(source_url)
            soup = bootstrap_adapter.parse(html)

            selected_adapter = detector.detect(source_url, html, soup)
            run_id = store.create_run(
                source_url,
                selected_adapter.name,
                county_name=source_metadata["county_name"],
                agency_key=source_metadata["agency_key"],
                module_name=source_metadata["module_name"],
            )
            store.save_source(
                source_url,
                selected_adapter.name,
                county_name=source_metadata["county_name"],
                agency_key=source_metadata["agency_key"],
                module_name=source_metadata["module_name"],
            )
            store.log(
                run_id,
                "INFO",
                "Adapter selected",
                {
                    "adapter": selected_adapter.name,
                    "county_name": source_metadata["county_name"],
                    "agency_key": source_metadata["agency_key"],
                    "module_name": source_metadata["module_name"],
                },
            )

            raw_items = selected_adapter.extract(source_url, html, soup)
            raw_batches = (
                selected_adapter.get_raw_batches()
                if hasattr(selected_adapter, "get_raw_batches")
                else [raw_items]
            )
            if not raw_items:
                store.log(run_id, "INFO", "No permits found", {})

            for raw_batch in raw_batches:
                if not raw_batch:
                    continue

                store.save_raw_result_batch(
                    county_name=source_metadata["county_name"],
                    agency_key=source_metadata["agency_key"],
                    module_name=source_metadata["module_name"],
                    source_url=source_url,
                    adapter_name=selected_adapter.name,
                    raw_items=raw_batch,
                )

                for raw in raw_batch:
                    normalized = selected_adapter.normalize(raw)
                    store.save_permit(
                        county_name=source_metadata["county_name"],
                        agency_key=source_metadata["agency_key"],
                        module_name=source_metadata["module_name"],
                        source_url=source_url,
                        adapter_name=selected_adapter.name,
                        normalized_data=normalized,
                        raw_data=raw,
                        crawl_status="success",
                    )

            if run_id is not None:
                store.complete_run(run_id, status="success")
            logger.info("Completed %s", source_url)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed %s", source_url)
            if run_id is not None:
                store.log(run_id, "ERROR", str(exc), {"url": source_url})
                store.complete_run(run_id, status="failed", error=str(exc))
            continue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal Permit Crawler")
    default_urls_file = Path(__file__).resolve().parent / "urls.txt"
    parser.add_argument(
        "--source",
        choices=("accela_constants", "file"),
        default="accela_constants",
        help="Where to load URLs from. Defaults to the Accela URLS constant.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Single URL to crawl (can be repeated)",
    )
    parser.add_argument(
        "--urls",
        default=str(default_urls_file),
        help="Path to a file containing one URL per line",
    )
    parser.add_argument(
        "--agency",
        action="append",
        default=[],
        help="Agency key from adapters/accela/constants.py, e.g. SAN_DIEGO or SACRAMENTO.",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Module name filter, e.g. Building, Planning, Enforcement.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Open Accela pages in a visible Playwright browser window.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of resolved URLs, useful for testing with 1 site.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.url:
        target_urls = args.url
    elif args.source == "accela_constants":
        target_urls = load_accela_urls(args.agency, args.module)
    else:
        target_urls = load_urls_from_file(args.urls)

    target_urls = limit_urls(target_urls, args.limit)

    if not target_urls:
        raise ValueError("No URLs were resolved. Check your constants, agency filters, or module filters.")

    crawl(target_urls, headed=args.headed)


if __name__ == "__main__":
    main()
