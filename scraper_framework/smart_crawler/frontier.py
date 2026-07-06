"""Queue management for multi-page crawls."""

from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, Set

from scraper_framework.smart_crawler.models import CrawlTarget
from scraper_framework.smart_crawler.url_tools import domain_for, normalize_url, same_domain


class CrawlFrontier:
    def __init__(self, seeds: Iterable[str], *, same_domain_only: bool):
        self.seed_domains = {domain_for(seed) for seed in seeds if domain_for(seed)}
        self.same_domain_only = same_domain_only
        self.queue: Deque[CrawlTarget] = deque()
        self.seen: Set[str] = set()
        self.visited: Set[str] = set()
        for seed in seeds:
            self.add(seed, depth=0, source="seed", parent_url=None)

    def add(self, url: str, *, depth: int, source: str, parent_url: str | None, priority: int = 0) -> bool:
        normalized = normalize_url(url)
        if not normalized or normalized in self.seen:
            return False
        if self.same_domain_only and not same_domain(normalized, self.seed_domains):
            return False
        self.seen.add(normalized)
        target = CrawlTarget(url=normalized, depth=depth, source=source, parent_url=parent_url, priority=priority)
        if priority > 0:
            self.queue.appendleft(target)
        else:
            self.queue.append(target)
        return True

    def pop(self) -> CrawlTarget | None:
        if not self.queue:
            return None
        return self.queue.popleft()

    def __len__(self) -> int:
        return len(self.queue)
