"""CLI entry point for the scraper framework."""

import argparse
from typing import Dict

from scraper_framework.config.settings import settings
from scraper_framework.services.site_a_service import SiteAService
from scraper_framework.services.site_b_service import SiteBService
from scraper_framework.utils.logger import configure_logger


def main() -> None:
    logger = configure_logger()
    parser = argparse.ArgumentParser(description="Scraper framework orchestrator")
    parser.add_argument("--site", choices=["site_a", "site_b"], required=True)
    parser.add_argument("--target", help="Target URL or API endpoint", required=True)
    parser.add_argument("--use-browser", action="store_true", help="Force browser rendering for site_b")
    args = parser.parse_args()

    service = SiteAService() if args.site == "site_a" else SiteBService()
    result = service.run(args.target, use_browser=args.use_browser, headers={"User-Agent": settings.user_agents[0]})

    logger.info("Scrape result: %s", result)


if __name__ == "__main__":
    main()
