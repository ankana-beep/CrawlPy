"""CLI entry point for the scraper framework."""

import argparse
from typing import Dict, Optional

from scraper_framework.config.settings import settings
from scraper_framework.db.connection import create_db_session
from scraper_framework.db.models import Base, ScrapedItem
from scraper_framework.services.site_a_service import SiteAService
from scraper_framework.services.site_b_service import SiteBService
from scraper_framework.utils.logger import configure_logger


def save_scrape_result(session_factory, target: str, result: Dict[str, Optional[str]]) -> None:
    session = session_factory()
    try:
        Base.metadata.create_all(bind=session.bind)
        item = ScrapedItem(
            url=target,
            title=result.get("title"),
            content=result.get("text"),
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
        session_factory = create_db_session()
        save_scrape_result(session_factory, args.target, result["result"])
        logger.info("Scrape result saved to database.")


if __name__ == "__main__":
    main()
