"""CLI entry point for the scraper framework."""

import argparse
import json
from typing import Dict, Optional

from scraper_framework.config.settings import settings
from scraper_framework.db.connection import create_db_session
from scraper_framework.db.models import Base, ScrapedItem
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


def save_scrape_result(session_factory, target: str, result: Dict[str, object]) -> None:
    session = session_factory()
    try:
        Base.metadata.create_all(bind=session.bind)
        extracted = result.get("result") if isinstance(result.get("result"), dict) else {}
        item = ScrapedItem(
            url=target,
            title=extracted.get("title") if isinstance(extracted, dict) else None,
            text=extracted.get("text") if isinstance(extracted, dict) else None,
            json_data=_json_safe(result),
        )
        session.add(item)
        session.commit()
    finally:
        session.close()


def main() -> None:
    logger = configure_logger()
    parser = argparse.ArgumentParser(description="Scraper framework orchestrator")
    parser.add_argument("--site", choices=["site_a", "site_b"], required=True)
    parser.add_argument("--target", help="Target URL or API endpoint", required=True)
    parser.add_argument("--use-browser", action="store_true", help="Force browser rendering for site_b")
    parser.add_argument("--save", action="store_true", help="Save scraped results to the configured database")
    args = parser.parse_args()

    service = SiteAService() if args.site == "site_a" else SiteBService()
    result = service.run(args.target, use_browser=args.use_browser, headers={"User-Agent": settings.user_agents[0]})

    logger.info("Scrape result: %s", result)

    if args.save:
        try:
            session_factory = create_db_session(settings.db_url)
            save_scrape_result(session_factory, args.target, result)
            logger.info("Scrape result saved to database via Postgres.")
        except Exception as postgres_error:
            logger.warning("Postgres save failed, attempting Supabase REST fallback: %s", postgres_error)
            supabase_client = SupabaseClient()
            extracted = result.get("result") if isinstance(result.get("result"), dict) else {}
            payload = {
                "url": args.target,
                "title": extracted.get("title") if isinstance(extracted, dict) else None,
            }
            if settings.supabase_text_column:
                payload[settings.supabase_text_column] = extracted.get("text") if isinstance(extracted, dict) else None
            if settings.supabase_json_column:
                payload[settings.supabase_json_column] = _json_safe(result)
            supabase_client.insert(payload)
            logger.info("Scrape result saved to Supabase REST.")


if __name__ == "__main__":
    main()
