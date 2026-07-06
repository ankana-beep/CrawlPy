"""robots.txt access checks."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser


def robots_url_for(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


@lru_cache(maxsize=256)
def _load_robot_parser(robots_url: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return parser
    return parser


class RobotsGuard:
    def __init__(self, user_agent: str, enabled: bool = True):
        self.user_agent = user_agent
        self.enabled = enabled

    def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parser = _load_robot_parser(robots_url_for(url))
        return parser.can_fetch(self.user_agent, url)
