"""CLI entry point for the scraper framework."""

import argparse
import json
from typing import Dict

from scraper_framework.config.settings import settings
from scraper_framework.db.supabase_client import SupabaseClient
from scraper_framework.services.site_a_service import SiteAService
from scraper_framework.services.site_b_service import SiteBService
from scraper_framework.utils.logger import configure_logger


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def main() -> None:
    logger = configure_logger()
    parser = argparse.ArgumentParser(description="Scraper framework orchestrator")
    parser.add_argument("--site", choices=["site_a", "site_b"], required=True)
    parser.add_argument("--target", help="Target URL or API endpoint", required=True)
    parser.add_argument("--use-browser", action="store_true", help="Force browser rendering for site_b")
    parser.add_argument("--timeout-ms", type=int, default=None, help="Browser navigation timeout (ms)")
    parser.add_argument(
        "--wait-until",
        choices=["commit", "domcontentloaded", "load", "networkidle"],
        default=None,
        help="Playwright wait_until mode for navigation",
    )
    parser.add_argument("--save", action="store_true", help="Save scraped results to the configured database")
    args = parser.parse_args()

    service = SiteAService() if args.site == "site_a" else SiteBService()
    result = service.run(
        args.target,
        use_browser=args.use_browser,
        headers={"User-Agent": settings.user_agents[0]},
        timeout_ms=args.timeout_ms,
        wait_until=args.wait_until,
    )

    logger.info("Scrape result: %s", result)

    if args.save:
        supabase_client = SupabaseClient()
        extracted = result.get("result") if isinstance(result.get("result"), dict) else {}
        payload: Dict[str, object] = {
            "url": args.target,
            "title": extracted.get("title") if isinstance(extracted, dict) else None,
        }
        if settings.supabase_text_column:
            payload[settings.supabase_text_column] = extracted.get("text") if isinstance(extracted, dict) else None
        if settings.supabase_json_column:
            payload[settings.supabase_json_column] = _json_safe(result)
        supabase_client.insert(payload)
        logger.info("Scrape result saved to Supabase.")


if __name__ == "__main__":
    main()
