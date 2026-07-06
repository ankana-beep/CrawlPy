"""CLI entry point for the scraper framework."""

import argparse
import json
from typing import Dict

from scraper_framework.config.settings import settings
from scraper_framework.db.mongo_client import MongoDBClient
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
    parser.add_argument("--site", choices=["site_a", "site_b", "accela_building"], required=True)
    parser.add_argument("--target", help="Target URL or API endpoint", required=True)
    parser.add_argument("--use-browser", action="store_true", help="Force browser rendering for site_b")
    parser.add_argument("--timeout-ms", type=int, default=None, help="Browser navigation timeout (ms)")
    parser.add_argument(
        "--wait-until",
        choices=["commit", "domcontentloaded", "load", "networkidle"],
        default=None,
        help="Playwright wait_until mode for navigation",
    )
    parser.add_argument("--permit-type-value", default=None, help="Accela permit type option value to select")
    parser.add_argument("--permit-type-label", default=None, help="Accela permit type visible label to select")
    parser.add_argument("--save", action="store_true", help="Save raw scraped results to MongoDB")
    args = parser.parse_args()

    if args.site == "site_a":
        from scraper_framework.services.site_a_service import SiteAService

        service = SiteAService()
    elif args.site == "site_b":
        from scraper_framework.services.site_b_service import SiteBService

        service = SiteBService()
    else:
        from scraper_framework.services.accela_building_service import AccelaBuildingService

        service = AccelaBuildingService()
    user_agent = settings.get_random_user_agent()

    try:
        result = service.run(
            args.target,
            use_browser=args.use_browser,
            headers={"User-Agent": user_agent},
            timeout_ms=args.timeout_ms,
            wait_until=args.wait_until,
            include_raw=args.save,
            permit_type_value=args.permit_type_value,
            permit_type_label=args.permit_type_label,
        )

        logger.info("Scrape result: %s", result)

        if not args.save:
            return

        mongo = MongoDBClient()
        try:
            doc: Dict[str, object] = {
                "target": args.target,
                "site": args.site,
                "raw": _json_safe(result),
            }
            inserted_id = mongo.insert_raw_scrape(doc)
            logger.info("Raw scrape saved to MongoDB (scrapes._id=%s).", inserted_id)
        finally:
            mongo.close()
    finally:
        close = getattr(service, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
