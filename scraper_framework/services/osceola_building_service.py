"""
Accela CitizenAccess Permit Scraper
====================================
Implements the pipeline from flowchart.mermaid:

  Job Manager -> Domain Normalizer -> Robots/Sitemap Checker -> Permission Checker
  -> URL Frontier -> Rate Limit Manager -> Page Fetch Orchestrator (Playwright)
  -> Page Classifier -> Content Normalizer -> Rule-based Extractor
  -> Schema Normalizer -> Validation/Cleaning -> Dedup -> MongoDB -> Export
  (+ Failure Handler -> Retry Queue, Logs + Metrics)

TARGET: Accela "Citizen Access" portals (permits.osceola.org and similar county
sites run on the same Accela platform). These are public-record search portals
(anyone can search permits without logging in) built on ASP.NET WebForms, which
means pagination happens via __doPostBack(), not by changing the URL. That's why
this uses Playwright instead of plain requests -- a GET request to page 2's URL
just returns page 1 again.

IMPORTANT - SELECTOR TUNING REQUIRED:
Every Accela instance customizes labels/module names, and grid element IDs are
auto-generated per deployment. The selectors below are the common Accela
defaults, but you MUST verify them against the live site once with
HEADLESS = False before trusting a big run. Search for "SELECTOR:" comments.

Install:
    pip install playwright pymongo tenacity
    playwright install chromium

Run:
    python accela_permit_scraper.py --site osceola --module Building --max-pages 50
"""

import argparse
import datetime as dt
import logging
import os
from pathlib import Path
import re
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote_plus
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("accela_scraper")

# ----------------------------------------------------------------------------
# CONFIG  (Job Manager input: multiple sites)
# ----------------------------------------------------------------------------

SITES = {
    "osceola": {
        "base_url": "https://permits.osceola.org/CitizenAccess/Cap/CapHome.aspx",
        "modules": ["Building"],   # add "Planning", "Code", etc. as needed
    },
    # "another_county": {"base_url": "https://permits.example.org/CitizenAccess/Cap/CapHome.aspx", "modules": ["Building"]},
}

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

def _build_mongo_uri_from_env() -> str:
    """Build Mongo URI from .env keys used in this project.

    Supported keys:
    - MONGODB_URI (full override)
    - MONGODB_SRV, MONGODB_HOST, MONGODB_USERNAME, MONGODB_PASSWORD,
      MONGODB_DB, MONGODB_PARAMS
    """
    explicit_uri = (os.getenv("MONGODB_URI") or "").strip()
    if explicit_uri:
        return explicit_uri

    host = (os.getenv("MONGODB_HOST") or "").strip()
    if not host:
        raise ValueError("MONGODB_HOST is required when MONGODB_URI is not set.")

    srv = (os.getenv("MONGODB_SRV", "true") or "").strip().lower() in {"1", "true", "yes", "y"}
    scheme = "mongodb+srv" if srv else "mongodb"

    username = (os.getenv("MONGODB_USERNAME") or "").strip()
    password = os.getenv("MONGODB_PASSWORD", "")
    auth = f"{quote_plus(username)}:{quote_plus(password)}@" if username else ""

    db_name = (os.getenv("MONGODB_DB", "crawlpy") or "").strip()
    db_path = f"/{db_name}" if db_name else ""

    params = (os.getenv("MONGODB_PARAMS") or "").strip()
    if params and not params.startswith("?"):
        params = "?" + params

    return f"{scheme}://{auth}{host}{db_path}{params}"


MONGO_DB = os.getenv("MONGODB_DB", "crawlpy")
MONGO_URI = _build_mongo_uri_from_env()

PAGE_LOAD_TIMEOUT_MS = 30_000
POST_ACTION_WAIT_MS = 1_500       # settle time after a postback
BATCH_SAVE_EVERY_N_PAGES = 10     # "page 1-10, save, then 11-20..." as you asked
MAX_RETRIES = 3
HEADLESS = False                  # set False the first time you tune selectors
USER_AGENT = "Mozilla/5.0 (compatible; PermitResearchBot/1.0; contact=you@example.com)"

# ----------------------------------------------------------------------------
# Domain Normalizer
# ----------------------------------------------------------------------------

def normalize_domain(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ----------------------------------------------------------------------------
# Robots.txt + Permission/Scope Checker
# ----------------------------------------------------------------------------

class PermissionChecker:
    """Checks robots.txt before we touch a domain. This is the
    'Permission + Scope Checker' box in the flowchart."""

    def __init__(self):
        self._cache: dict[str, robotparser.RobotFileParser] = {}

    def _get_parser(self, domain: str) -> robotparser.RobotFileParser:
        if domain not in self._cache:
            rp = robotparser.RobotFileParser()
            rp.set_url(urljoin(domain, "/robots.txt"))
            try:
                rp.read()
            except Exception as e:
                log.warning("Could not read robots.txt for %s (%s); assuming allowed.", domain, e)
                rp = None
            self._cache[domain] = rp
        return self._cache[domain]

    def is_allowed(self, url: str, user_agent: str = USER_AGENT) -> tuple[bool, str]:
        domain = normalize_domain(url)
        rp = self._get_parser(domain)
        if rp is None:
            return True, "robots.txt unavailable, defaulting to allow"
        allowed = rp.can_fetch(user_agent, url)
        reason = "allowed by robots.txt" if allowed else "disallowed by robots.txt"
        return allowed, reason


# ----------------------------------------------------------------------------
# MongoDB storage (Schema Normalizer output target + Dedup)
# ----------------------------------------------------------------------------

class MongoStore:
    def __init__(self, uri: str, db_name: str):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]

    def collection(self, site: str, module: str):
        return self.db[f"{site}_{module}".lower()]

    def upsert_records(self, site: str, module: str, records: list[dict]) -> int:
        if not records:
            return 0
        coll = self.collection(site, module)
        coll.create_index("record_number", unique=True, sparse=True)
        ops = []
        for rec in records:
            key = rec.get("record_number") or rec.get("_dedup_key")
            if not key:
                continue
            rec["scraped_at"] = dt.datetime.utcnow()
            ops.append(UpdateOne({"record_number": key}, {"$set": rec}, upsert=True))
        if not ops:
            return 0
        try:
            result = coll.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except PyMongoError as e:
            log.error("Mongo bulk_write failed: %s", e)
            return 0

    def log_event(self, site: str, level: str, message: str, extra: Optional[dict] = None):
        self.db["logs"].insert_one({
            "site": site,
            "level": level,
            "message": message,
            "extra": extra or {},
            "ts": dt.datetime.utcnow(),
        })


# ----------------------------------------------------------------------------
# Page Classifier + Rule-based Extractor
# ----------------------------------------------------------------------------

@dataclass
class ExtractedPage:
    records: list[dict] = field(default_factory=list)
    has_next: bool = False


class AccelaExtractor:
    """Pulls rows out of the Accela results grid. Accela renders results as a
    plain HTML <table> with header <th>/<td> cells; column names become the
    dict keys, normalized to snake_case."""

    HEADER_ALIASES = {
        "issue_date": {"issue date", "date", "opened date", "filed date"},
        "record_number": {"record number", "permit number", "record #", "permit #", "application number"},
        "record_type": {"record type", "permit type", "type"},
        "project_name": {"project name", "project"},
        "address": {"address", "site address", "property address"},
        "status": {"status"},
        "action": {"action"},
        "description": {"description", "work description", "scope of work"},
        "expiration_date": {"expiration date", "expire date"},
        "short_notes": {"short notes", "notes"},
        "applicant": {"applicant", "applicant name", "owner", "contractor"},
    }
    SITE_HEADER_ALIASES: dict[str, dict[str, set[str]]] = {}
    PREFERRED_COLUMNS = [
        "issue_date",
        "record_number",
        "record_type",
        "project_name",
        "address",
        "status",
        "action",
        "description",
        "expiration_date",
        "short_notes",
        "applicant",
    ]

    def __init__(self, site: Optional[str] = None):
        self.site = (site or "").strip().lower()
        self._header_lookup = self._build_header_lookup(self.site)

    @staticmethod
    def _normalize_header_label(header_text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (header_text or "").strip().lower()).strip()

    @classmethod
    def _build_header_lookup(cls, site: str) -> dict[str, str]:
        lookup: dict[str, str] = {}
        merged: dict[str, set[str]] = {k: set(v) for k, v in cls.HEADER_ALIASES.items()}
        site_aliases = cls.SITE_HEADER_ALIASES.get(site, {})
        for key, aliases in site_aliases.items():
            merged.setdefault(key, set()).update(aliases)

        for canonical, aliases in merged.items():
            lookup[cls._normalize_header_label(canonical)] = canonical
            for alias in aliases:
                lookup[cls._normalize_header_label(alias)] = canonical
        return lookup

    def _normalize_key(self, header_text: str) -> str:
        normalized = self._normalize_header_label(header_text)
        if normalized in self._header_lookup:
            return self._header_lookup[normalized]
        return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")

    @staticmethod
    def _is_pagination_token(value: str) -> bool:
        token = value.strip().lower()
        if not token:
            return True
        if token in {"< prev", "prev", "next >", "next", "..."}:
            return True
        if token.isdigit():
            return True
        return False

    @classmethod
    def _is_pagination_row(cls, values: list[str], row_text: str) -> bool:
        compact = " ".join(values).strip()
        low = (row_text or compact).lower()
        if "prev" in low and "next" in low:
            tokens = [v for v in values if v.strip()]
            if tokens and all(cls._is_pagination_token(v) for v in tokens):
                return True
        if compact and all(cls._is_pagination_token(v) for v in values if v.strip()):
            return True
        return False

    @staticmethod
    def _extract_record_link(row) -> tuple[Optional[str], Optional[str]]:
        links = row.query_selector_all("a")
        for link in links:
            text = (link.inner_text() or "").strip()
            low = text.lower()
            if not text:
                continue
            if low in {"< prev", "prev", "next >", "next", "..."} or text.isdigit():
                continue

            href = link.get_attribute("href")
            if href:
                return text, href
            return text, None
        return None, None

    @staticmethod
    def _find_record_number(values: list[str]) -> Optional[str]:
        for value in values:
            match = re.search(r"\b[A-Za-z]{1,8}\d{0,4}-\d{3,}\b", value or "")
            if match:
                return match.group(0)
        return None

    @classmethod
    def _map_row_values(cls, headers: list[str], values: list[str]) -> dict[str, str]:
        rec: dict[str, str] = {}

        # Best case: header count aligns with cell count.
        if headers and len(headers) == len(values):
            for key, value in zip(headers, values):
                if key:
                    rec[key] = value
            return rec

        # Fallback for Accela layouts with a leading checkbox + extra hidden cells.
        start_idx = 1 if values and not values[0].strip() else 0
        trimmed = values[start_idx:]
        for idx, key in enumerate(cls.PREFERRED_COLUMNS):
            if idx >= len(trimmed):
                break
            rec[key] = trimmed[idx]

        # Overlay any usable header matches even if counts differ.
        for key, value in zip(headers, values):
            if key and key in cls.PREFERRED_COLUMNS and key not in rec:
                rec[key] = value

        return rec

    def extract(self, page: Page) -> ExtractedPage:
        # SELECTOR: Accela grids commonly use a table with id ending in
        # "...gdvPermitList" or class "ACA_Grid". Try both, fall back to
        # "the biggest table on the page with a header row".
        table = page.query_selector("table[id*='gdvPermitList']") \
            or page.query_selector("table.ACA_Grid") \
            or self._largest_data_table(page)

        if table is None:
            return ExtractedPage(records=[], has_next=False)

        header_elements = table.query_selector_all("thead th, tr:first-child th")
        raw_headers = [(th.inner_text() or "").strip() for th in header_elements]
        headers = [self._normalize_key(h) for h in raw_headers]

        # Accela usually marks result rows with Odd/Even classes. Prefer these to avoid pager rows.
        rows = table.query_selector_all("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")
        if not rows:
            rows = table.query_selector_all("tbody tr, tr:not(:first-child)")

        records = []
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells:
                continue
            values = [c.inner_text().strip() for c in cells]
            row_text = " ".join(values)
            if self._is_pagination_row(values, row_text):
                continue

            rec = self._map_row_values(headers, values)
            raw_fields: dict[str, str] = {}
            for header_text, value in zip(raw_headers, values):
                if header_text:
                    raw_fields[header_text] = value
            if raw_fields:
                rec["raw_fields"] = raw_fields

            link_text, href = self._extract_record_link(row)
            if href:
                rec["detail_url"] = urljoin(page.url, href)

            record_number = rec.get("record_number")
            if not record_number:
                record_number = link_text or self._find_record_number(values)
            rec["record_number"] = str(record_number).strip() if record_number else None

            # Guardrail: skip non-record rows that still slipped through.
            if not rec.get("record_number"):
                continue
            if self._is_pagination_token(str(rec.get("record_number"))):
                continue

            if any(rec.values()):
                records.append(rec)

        has_next = self._has_next_page(page)
        return ExtractedPage(records=records, has_next=has_next)

    def _largest_data_table(self, page: Page):
        tables = page.query_selector_all("table")
        best, best_rows = None, 0
        for t in tables:
            n = len(t.query_selector_all("tr"))
            if n > best_rows:
                best, best_rows = t, n
        return best if best_rows > 1 else None

    def _has_next_page(self, page: Page) -> bool:
        # SELECTOR: Accela pagination usually renders as a link/button with
        # text like "Next" or a ">" glyph, disabled (or absent) on the last page.
        next_link = page.query_selector(
            "a:has-text('Next'), a[title='Next'], a.aca_pagination_next, input[value='Next']"
        )
        if next_link is None:
            return False
        disabled = next_link.get_attribute("disabled")
        classes = next_link.get_attribute("class") or ""
        return disabled is None and "disabled" not in classes


# ----------------------------------------------------------------------------
# Page Fetch Orchestrator + Rate Limit Manager + Failure Handler/Retry
# ----------------------------------------------------------------------------

class AccelaScraper:
    def __init__(self, site: str, base_url: str, module: str, store: MongoStore,
                 permission_checker: PermissionChecker, max_pages: int = 100,
                 delay_seconds: float = 2.0):
        self.site = site
        self.base_url = base_url
        self.module = module
        self.store = store
        self.permission_checker = permission_checker
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.extractor = AccelaExtractor(site=site)

    def run(self):
        search_url = f"{self.base_url}?module={self.module}"

        allowed, reason = self.permission_checker.is_allowed(search_url)
        if not allowed:
            log.warning("Skipping %s: %s", search_url, reason)
            self.store.log_event(self.site, "SKIP", reason, {"url": search_url})
            return

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=HEADLESS)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()

            try:
                self._open_search(page, search_url)
                self._run_general_search(page)
                self._paginate_and_scrape(page)
            except Exception as e:
                log.exception("Fatal error scraping %s/%s", self.site, self.module)
                self.store.log_event(self.site, "ERROR", str(e), {"module": self.module})
            finally:
                browser.close()

    @retry(stop=stop_after_attempt(MAX_RETRIES),
           wait=wait_exponential(multiplier=2, min=2, max=30),
           retry=retry_if_exception_type(PWTimeout))
    def _open_search(self, page: Page, url: str):
        log.info("Opening %s", url)
        page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="networkidle")

    def _discover_search_controls(self, page: Page) -> list[dict[str, Any]]:
        controls = page.evaluate(
            """() => {
                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === "hidden" || style.display === "none") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function buildXPath(el) {
                    if (!el || el.nodeType !== 1) return "";
                    if (el.id) return `//*[@id="${el.id}"]`;

                    const parts = [];
                    let node = el;
                    while (node && node.nodeType === 1) {
                        let ix = 1;
                        let sib = node.previousElementSibling;
                        while (sib) {
                            if (sib.tagName === node.tagName) ix += 1;
                            sib = sib.previousElementSibling;
                        }
                        parts.unshift(`${node.tagName.toLowerCase()}[${ix}]`);
                        node = node.parentElement;
                    }
                    return "/" + parts.join("/");
                }

                function textFor(el) {
                    const val = (el.value || "").trim();
                    const txt = (el.innerText || el.textContent || "").trim();
                    return val || txt;
                }

                const selectors = [
                    "input[type='submit']",
                    "input[type='button']",
                    "input[value*='Search' i]",
                    "button",
                    "a",
                    "[id*='Search' i]",
                    "[title*='Search' i]",
                ];

                const seen = new Set();
                const candidates = [];

                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);

                        const id = el.id || "";
                        const title = el.getAttribute("title") || "";
                        const tag = (el.tagName || "").toLowerCase();
                        const text = textFor(el);
                        const hay = `${id} ${title} ${text}`.toLowerCase();
                        if (!hay.includes("search")) continue;

                        const visible = isVisible(el);
                        const enabled = !el.disabled && el.getAttribute("aria-disabled") !== "true";

                        let score = 0;
                        if (visible) score += 100;
                        if (enabled) score += 50;
                        if (id.toLowerCase().includes("btnnewsearch")) score += 40;
                        if (id.toLowerCase().includes("search")) score += 30;
                        if (text.toLowerCase() === "search") score += 25;
                        if (tag === "input" || tag === "button") score += 10;

                        candidates.push({
                            tag,
                            id,
                            title,
                            text,
                            visible,
                            enabled,
                            score,
                            xpath: buildXPath(el),
                            outer_html: (el.outerHTML || "").slice(0, 600),
                        });
                    }
                }

                candidates.sort((a, b) => b.score - a.score);
                return candidates;
            }"""
        )
        return controls if isinstance(controls, list) else []

    def _run_general_search(self, page: Page):
        """Submits the General Search with no filters to return all records
        for the module. SELECTOR: adjust the search-button id/text to match
        the live page (inspect via HEADLESS=False)."""
        candidates = self._discover_search_controls(page)
        if not candidates:
            log.warning("No visible search button found; assuming results are already on this page.")
            return

        for idx, c in enumerate(candidates[:5], start=1):
            log.info(
                "Search candidate #%d score=%s visible=%s enabled=%s xpath=%s outerHTML=%s",
                idx,
                c.get("score"),
                c.get("visible"),
                c.get("enabled"),
                c.get("xpath"),
                c.get("outer_html"),
            )

        clicked = False
        for c in candidates:
            if not (c.get("visible") and c.get("enabled")):
                continue
            xpath = c.get("xpath")
            if not xpath:
                continue
            try:
                page.locator(f"xpath={xpath}").first.click(timeout=10_000)
                log.info("Clicked search via xpath=%s text=%s id=%s", xpath, c.get("text"), c.get("id"))
                clicked = True
                break
            except Exception:
                try:
                    clicked_via_js = page.evaluate(
                        """(xp) => {
                            const node = document.evaluate(
                                xp,
                                document,
                                null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE,
                                null
                            ).singleNodeValue;
                            if (!node) return false;
                            node.click();
                            return true;
                        }""",
                        xpath,
                    )
                    if clicked_via_js:
                        log.info("Clicked search via JS xpath fallback=%s", xpath)
                        clicked = True
                        break
                except Exception:
                    continue

        if not clicked:
            log.warning("Found search candidates but none were clickable; continuing without clicking search.")
            return

        page.wait_for_timeout(POST_ACTION_WAIT_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)

    def _paginate_and_scrape(self, page: Page):
        page_num = 1
        batch: list[dict] = []
        total_saved = 0

        while page_num <= self.max_pages:
            log.info("[%s/%s] Extracting page %d", self.site, self.module, page_num)
            extracted = self._extract_with_retry(page)
            batch.extend(extracted.records)
            log.info("Page %d yielded %d records (running batch=%d)",
                      page_num, len(extracted.records), len(batch))

            if page_num % BATCH_SAVE_EVERY_N_PAGES == 0 or not extracted.has_next:
                saved = self.store.upsert_records(self.site, self.module, batch)
                total_saved += saved
                log.info("Saved batch through page %d (%d upserted, %d total)",
                         page_num, saved, total_saved)
                batch = []

            if not extracted.has_next:
                log.info("No further pages detected. Stopping at page %d.", page_num)
                break

            self._click_next(page)
            time.sleep(self.delay_seconds)  # Rate Limit Manager: be polite
            page_num += 1

        if batch:
            saved = self.store.upsert_records(self.site, self.module, batch)
            total_saved += saved
            log.info("Final partial batch saved (%d upserted).", saved)

        self.store.log_event(self.site, "INFO", "scrape complete",
                              {"module": self.module, "pages": page_num, "records_saved": total_saved})

    @retry(stop=stop_after_attempt(MAX_RETRIES),
           wait=wait_exponential(multiplier=2, min=2, max=20))
    def _extract_with_retry(self, page: Page) -> ExtractedPage:
        return self.extractor.extract(page)

    @retry(stop=stop_after_attempt(MAX_RETRIES),
           wait=wait_exponential(multiplier=2, min=2, max=20))
    def _click_next(self, page: Page):
        next_link = page.query_selector(
            "a:has-text('Next'), a[title='Next'], a.aca_pagination_next, input[value='Next']"
        )
        if next_link is None:
            raise RuntimeError("Expected a 'Next' control but found none.")
        next_link.click()
        page.wait_for_timeout(POST_ACTION_WAIT_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)


# ----------------------------------------------------------------------------
# Job Manager (entry point)
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Accela CitizenAccess permit scraper")
    parser.add_argument("--site", choices=list(SITES.keys()), default="osceola")
    parser.add_argument("--module", default=None, help="Override module (e.g. Building, Planning)")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between page requests")
    args = parser.parse_args()

    site_cfg = SITES[args.site]
    modules = [args.module] if args.module else site_cfg["modules"]

    store = MongoStore(MONGO_URI, MONGO_DB)
    permission_checker = PermissionChecker()

    for module in modules:
        scraper = AccelaScraper(
            site=args.site,
            base_url=site_cfg["base_url"],
            module=module,
            store=store,
            permission_checker=permission_checker,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
        )
        scraper.run()


if __name__ == "__main__":
    main()
