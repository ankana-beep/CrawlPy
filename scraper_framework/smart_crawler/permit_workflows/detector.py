"""Portal type and permit workflow heuristics."""

from __future__ import annotations

from scraper_framework.smart_crawler.models import ExtractedPage


PORTAL_HINTS = {
    "iworq": ("iworq", "portal.iworq.net"),
    "accela": ("accela", "aca-prod", "cap/caphome"),
    "energov": ("energov", "egov", "cssenergov"),
    "cityview": ("cityview",),
}


def detect_portal_type(url: str, extracted: ExtractedPage | None = None) -> str:
    text = url.lower()
    if extracted:
        text = " ".join([text, extracted.title or "", extracted.text[:5000] or ""]).lower()
    for portal_type, hints in PORTAL_HINTS.items():
        if any(hint in text for hint in hints):
            return portal_type
    return "generic"


def should_run_workflow(url: str, extracted: ExtractedPage) -> bool:
    if extracted.forms:
        return True
    text = " ".join([url, extracted.title or "", extracted.text[:8000] or ""]).lower()
    return any(
        hint in text
        for hint in (
            "permit search",
            "building permit",
            "record search",
            "application search",
            "inspection search",
            "iworq",
            "accela",
            "energov",
            "cityview",
        )
    )
