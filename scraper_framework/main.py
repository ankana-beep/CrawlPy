from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

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


def crawl(urls: Iterable[str]) -> None:
    adapters: list[BaseAdapter] = build_adapters()
    detector = AdapterDetector(adapters)
    store = MongoStore()

    for source_url in urls:
        source_url = source_url.strip()
        if not source_url:
            continue

        run_id = None
        logger.info("Crawling %s", source_url)

        try:
            bootstrap_adapter = adapters[0]
            html = bootstrap_adapter.fetch_html(source_url)
            soup = bootstrap_adapter.parse(html)

            selected_adapter = detector.detect(source_url, html, soup)
            run_id = store.create_run(source_url, selected_adapter.name)
            store.save_source(source_url, selected_adapter.name)
            store.log(run_id, "INFO", "Adapter selected", {"adapter": selected_adapter.name})

            raw_items = selected_adapter.extract(source_url, html, soup)
            if not raw_items:
                store.log(run_id, "INFO", "No permits found", {})

            for raw in raw_items:
                normalized = selected_adapter.normalize(raw)
                store.save_permit(
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.url:
        target_urls = args.url
    else:
        target_urls = load_urls_from_file(args.urls)

    crawl(target_urls)


if __name__ == "__main__":
    main()
