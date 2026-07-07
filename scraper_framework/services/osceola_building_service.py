# """
# Accela CitizenAccess Permit Scraper
# ====================================
# Implements the pipeline from flowchart.mermaid:

#   Job Manager -> Domain Normalizer -> Robots/Sitemap Checker -> Permission Checker
#   -> URL Frontier -> Rate Limit Manager -> Page Fetch Orchestrator (Playwright)
#   -> Page Classifier -> Content Normalizer -> Rule-based Extractor
#   -> Schema Normalizer -> Validation/Cleaning -> Dedup -> MongoDB -> Export
#   (+ Failure Handler -> Retry Queue, Logs + Metrics)

# TARGET: Accela "Citizen Access" portals (permits.osceola.org and similar county
# sites run on the same Accela platform). These are public-record search portals
# (anyone can search permits without logging in) built on ASP.NET WebForms, which
# means pagination happens via __doPostBack(), not by changing the URL. That's why
# this uses Playwright instead of plain requests -- a GET request to page 2's URL
# just returns page 1 again.

# IMPORTANT - SELECTOR TUNING REQUIRED:
# Every Accela instance customizes labels/module names, and grid element IDs are
# auto-generated per deployment. The selectors below are the common Accela
# defaults, but you MUST verify them against the live site once with
# HEADLESS = False before trusting a big run. Search for "SELECTOR:" comments.

# Install:
#     pip install playwright pymongo tenacity
#     playwright install chromium

# Run:
#     python accela_permit_scraper.py --site osceola --module Building --max-pages 50
# """

# import argparse
# import datetime as dt
# import logging
# import os
# from pathlib import Path
# import re
# import time
# import urllib.robotparser as robotparser
# from dataclasses import dataclass, field
# from typing import Any, Optional
# from urllib.parse import quote_plus
# from urllib.parse import urljoin, urlparse

# from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
# from pymongo import MongoClient, UpdateOne
# from pymongo.errors import PyMongoError
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# from dotenv import load_dotenv

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
# )
# log = logging.getLogger("accela_scraper")

# # ----------------------------------------------------------------------------
# # CONFIG  (Job Manager input: multiple sites)
# # ----------------------------------------------------------------------------

# SITES = {
#     "osceola": {
#         "base_url": "https://permits.osceola.org/CitizenAccess/Cap/CapHome.aspx",
#         "modules": ["Building"],   # add "Planning", "Code", etc. as needed
#     },
#     # "another_county": {"base_url": "https://permits.example.org/CitizenAccess/Cap/CapHome.aspx", "modules": ["Building"]},
# }

# load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

# def _build_mongo_uri_from_env() -> str:
#     """Build Mongo URI from .env keys used in this project.

#     Supported keys:
#     - MONGODB_URI (full override)
#     - MONGODB_SRV, MONGODB_HOST, MONGODB_USERNAME, MONGODB_PASSWORD,
#       MONGODB_DB, MONGODB_PARAMS
#     """
#     explicit_uri = (os.getenv("MONGODB_URI") or "").strip()
#     if explicit_uri:
#         return explicit_uri

#     host = (os.getenv("MONGODB_HOST") or "").strip()
#     if not host:
#         raise ValueError("MONGODB_HOST is required when MONGODB_URI is not set.")

#     srv = (os.getenv("MONGODB_SRV", "true") or "").strip().lower() in {"1", "true", "yes", "y"}
#     scheme = "mongodb+srv" if srv else "mongodb"

#     username = (os.getenv("MONGODB_USERNAME") or "").strip()
#     password = os.getenv("MONGODB_PASSWORD", "")
#     auth = f"{quote_plus(username)}:{quote_plus(password)}@" if username else ""

#     db_name = (os.getenv("MONGODB_DB", "crawlpy") or "").strip()
#     db_path = f"/{db_name}" if db_name else ""

#     params = (os.getenv("MONGODB_PARAMS") or "").strip()
#     if params and not params.startswith("?"):
#         params = "?" + params

#     return f"{scheme}://{auth}{host}{db_path}{params}"


# MONGO_DB = os.getenv("MONGODB_DB", "crawlpy")
# MONGO_URI = _build_mongo_uri_from_env()

# PAGE_LOAD_TIMEOUT_MS = 30_000
# POST_ACTION_WAIT_MS = 1_500       # settle time after a postback
# BATCH_SAVE_EVERY_N_PAGES = 10     # "page 1-10, save, then 11-20..." as you asked
# MAX_RETRIES = 3
# HEADLESS = False                  # set False the first time you tune selectors
# USER_AGENT = "Mozilla/5.0 (compatible; PermitResearchBot/1.0; contact=you@example.com)"

# # ----------------------------------------------------------------------------
# # Domain Normalizer
# # ----------------------------------------------------------------------------

# def normalize_domain(url: str) -> str:
#     parsed = urlparse(url)
#     return f"{parsed.scheme}://{parsed.netloc}"


# # ----------------------------------------------------------------------------
# # Robots.txt + Permission/Scope Checker
# # ----------------------------------------------------------------------------

# class PermissionChecker:
#     """Checks robots.txt before we touch a domain. This is the
#     'Permission + Scope Checker' box in the flowchart."""

#     def __init__(self):
#         self._cache: dict[str, robotparser.RobotFileParser] = {}

#     def _get_parser(self, domain: str) -> robotparser.RobotFileParser:
#         if domain not in self._cache:
#             rp = robotparser.RobotFileParser()
#             rp.set_url(urljoin(domain, "/robots.txt"))
#             try:
#                 rp.read()
#             except Exception as e:
#                 log.warning("Could not read robots.txt for %s (%s); assuming allowed.", domain, e)
#                 rp = None
#             self._cache[domain] = rp
#         return self._cache[domain]

#     def is_allowed(self, url: str, user_agent: str = USER_AGENT) -> tuple[bool, str]:
#         domain = normalize_domain(url)
#         rp = self._get_parser(domain)
#         if rp is None:
#             return True, "robots.txt unavailable, defaulting to allow"
#         allowed = rp.can_fetch(user_agent, url)
#         reason = "allowed by robots.txt" if allowed else "disallowed by robots.txt"
#         return allowed, reason


# # ----------------------------------------------------------------------------
# # MongoDB storage (Schema Normalizer output target + Dedup)
# # ----------------------------------------------------------------------------

# class MongoStore:
#     def __init__(self, uri: str, db_name: str):
#         self.client = MongoClient(uri)
#         self.db = self.client[db_name]

#     def collection(self, site: str, module: str):
#         return self.db[f"{site}_{module}".lower()]

#     def upsert_records(self, site: str, module: str, records: list[dict]) -> int:
#         if not records:
#             return 0
#         coll = self.collection(site, module)
#         coll.create_index("record_number", unique=True, sparse=True)
#         ops = []
#         for rec in records:
#             key = rec.get("record_number") or rec.get("_dedup_key")
#             if not key:
#                 continue
#             rec["scraped_at"] = dt.datetime.utcnow()
#             ops.append(UpdateOne({"record_number": key}, {"$set": rec}, upsert=True))
#         if not ops:
#             return 0
#         try:
#             result = coll.bulk_write(ops, ordered=False)
#             return result.upserted_count + result.modified_count
#         except PyMongoError as e:
#             log.error("Mongo bulk_write failed: %s", e)
#             return 0

#     def log_event(self, site: str, level: str, message: str, extra: Optional[dict] = None):
#         self.db["logs"].insert_one({
#             "site": site,
#             "level": level,
#             "message": message,
#             "extra": extra or {},
#             "ts": dt.datetime.utcnow(),
#         })


# # ----------------------------------------------------------------------------
# # Page Classifier + Rule-based Extractor
# # ----------------------------------------------------------------------------

# @dataclass
# class ExtractedPage:
#     records: list[dict] = field(default_factory=list)
#     has_next: bool = False


# class AccelaExtractor:
#     """Pulls rows out of the Accela results grid. Accela renders results as a
#     plain HTML <table> with header <th>/<td> cells; column names become the
#     dict keys, normalized to snake_case."""

#     HEADER_ALIASES = {
#         "issue_date": {"issue date", "date", "opened date", "filed date"},
#         "record_number": {"record number", "permit number", "record #", "permit #", "application number"},
#         "record_type": {"record type", "permit type", "type"},
#         "project_name": {"project name", "project"},
#         "address": {"address", "site address", "property address"},
#         "status": {"status"},
#         "action": {"action"},
#         "description": {"description", "work description", "scope of work"},
#         "expiration_date": {"expiration date", "expire date"},
#         "short_notes": {"short notes", "notes"},
#         "applicant": {"applicant", "applicant name", "owner", "contractor"},
#     }
#     SITE_HEADER_ALIASES: dict[str, dict[str, set[str]]] = {}
#     PREFERRED_COLUMNS = [
#         "issue_date",
#         "record_number",
#         "record_type",
#         "project_name",
#         "address",
#         "status",
#         "action",
#         "description",
#         "expiration_date",
#         "short_notes",
#         "applicant",
#     ]

#     def __init__(self, site: Optional[str] = None):
#         self.site = (site or "").strip().lower()
#         self._header_lookup = self._build_header_lookup(self.site)

#     @staticmethod
#     def _normalize_header_label(header_text: str) -> str:
#         return re.sub(r"[^a-z0-9]+", " ", (header_text or "").strip().lower()).strip()

#     @classmethod
#     def _build_header_lookup(cls, site: str) -> dict[str, str]:
#         lookup: dict[str, str] = {}
#         merged: dict[str, set[str]] = {k: set(v) for k, v in cls.HEADER_ALIASES.items()}
#         site_aliases = cls.SITE_HEADER_ALIASES.get(site, {})
#         for key, aliases in site_aliases.items():
#             merged.setdefault(key, set()).update(aliases)

#         for canonical, aliases in merged.items():
#             lookup[cls._normalize_header_label(canonical)] = canonical
#             for alias in aliases:
#                 lookup[cls._normalize_header_label(alias)] = canonical
#         return lookup

#     def _normalize_key(self, header_text: str) -> str:
#         normalized = self._normalize_header_label(header_text)
#         if normalized in self._header_lookup:
#             return self._header_lookup[normalized]
#         return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")

#     @staticmethod
#     def _is_pagination_token(value: str) -> bool:
#         token = value.strip().lower()
#         if not token:
#             return True
#         if token in {"< prev", "prev", "next >", "next", "..."}:
#             return True
#         if token.isdigit():
#             return True
#         return False

#     @classmethod
#     def _is_pagination_row(cls, values: list[str], row_text: str) -> bool:
#         compact = " ".join(values).strip()
#         low = (row_text or compact).lower()
#         if "prev" in low and "next" in low:
#             tokens = [v for v in values if v.strip()]
#             if tokens and all(cls._is_pagination_token(v) for v in tokens):
#                 return True
#         if compact and all(cls._is_pagination_token(v) for v in values if v.strip()):
#             return True
#         return False

#     @staticmethod
#     def _extract_record_link(row) -> tuple[Optional[str], Optional[str]]:
#         links = row.query_selector_all("a")
#         for link in links:
#             text = (link.inner_text() or "").strip()
#             low = text.lower()
#             if not text:
#                 continue
#             if low in {"< prev", "prev", "next >", "next", "..."} or text.isdigit():
#                 continue

#             href = link.get_attribute("href")
#             if href:
#                 return text, href
#             return text, None
#         return None, None

#     @staticmethod
#     def _find_record_number(values: list[str]) -> Optional[str]:
#         for value in values:
#             match = re.search(r"\b[A-Za-z]{1,8}\d{0,4}-\d{3,}\b", value or "")
#             if match:
#                 return match.group(0)
#         return None

#     @classmethod
#     def _map_row_values(cls, headers: list[str], values: list[str]) -> dict[str, str]:
#         rec: dict[str, str] = {}

#         # Best case: header count aligns with cell count.
#         if headers and len(headers) == len(values):
#             for key, value in zip(headers, values):
#                 if key:
#                     rec[key] = value
#             return rec

#         # Fallback for Accela layouts with a leading checkbox + extra hidden cells.
#         start_idx = 1 if values and not values[0].strip() else 0
#         trimmed = values[start_idx:]
#         for idx, key in enumerate(cls.PREFERRED_COLUMNS):
#             if idx >= len(trimmed):
#                 break
#             rec[key] = trimmed[idx]

#         # Overlay any usable header matches even if counts differ.
#         for key, value in zip(headers, values):
#             if key and key in cls.PREFERRED_COLUMNS and key not in rec:
#                 rec[key] = value

#         return rec

#     def extract(self, page: Page) -> ExtractedPage:
#         # SELECTOR: Accela grids commonly use a table with id ending in
#         # "...gdvPermitList" or class "ACA_Grid". Try both, fall back to
#         # "the biggest table on the page with a header row".
#         table = page.query_selector("table[id*='gdvPermitList']") \
#             or page.query_selector("table.ACA_Grid") \
#             or self._largest_data_table(page)

#         if table is None:
#             return ExtractedPage(records=[], has_next=False)

#         header_elements = table.query_selector_all("thead th, tr:first-child th")
#         raw_headers = [(th.inner_text() or "").strip() for th in header_elements]
#         headers = [self._normalize_key(h) for h in raw_headers]

#         # Accela usually marks result rows with Odd/Even classes. Prefer these to avoid pager rows.
#         rows = table.query_selector_all("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")
#         if not rows:
#             rows = table.query_selector_all("tbody tr, tr:not(:first-child)")

#         records = []
#         for row in rows:
#             cells = row.query_selector_all("td")
#             if not cells:
#                 continue
#             values = [c.inner_text().strip() for c in cells]
#             row_text = " ".join(values)
#             if self._is_pagination_row(values, row_text):
#                 continue

#             rec = self._map_row_values(headers, values)
#             raw_fields: dict[str, str] = {}
#             for header_text, value in zip(raw_headers, values):
#                 if header_text:
#                     raw_fields[header_text] = value
#             if raw_fields:
#                 rec["raw_fields"] = raw_fields

#             link_text, href = self._extract_record_link(row)
#             if href:
#                 rec["detail_url"] = urljoin(page.url, href)

#             record_number = rec.get("record_number")
#             if not record_number:
#                 record_number = link_text or self._find_record_number(values)
#             rec["record_number"] = str(record_number).strip() if record_number else None

#             # Guardrail: skip non-record rows that still slipped through.
#             if not rec.get("record_number"):
#                 continue
#             if self._is_pagination_token(str(rec.get("record_number"))):
#                 continue

#             if any(rec.values()):
#                 records.append(rec)

#         has_next = self._has_next_page(page)
#         return ExtractedPage(records=records, has_next=has_next)

#     def _largest_data_table(self, page: Page):
#         tables = page.query_selector_all("table")
#         best, best_rows = None, 0
#         for t in tables:
#             n = len(t.query_selector_all("tr"))
#             if n > best_rows:
#                 best, best_rows = t, n
#         return best if best_rows > 1 else None

#     def _has_next_page(self, page: Page) -> bool:
#         # SELECTOR: Accela pagination usually renders as a link/button with
#         # text like "Next" or a ">" glyph, disabled (or absent) on the last page.
#         next_link = page.query_selector(
#             "a:has-text('Next'), a[title='Next'], a.aca_pagination_next, input[value='Next']"
#         )
#         if next_link is None:
#             return False
#         disabled = next_link.get_attribute("disabled")
#         classes = next_link.get_attribute("class") or ""
#         return disabled is None and "disabled" not in classes


# # ----------------------------------------------------------------------------
# # Page Fetch Orchestrator + Rate Limit Manager + Failure Handler/Retry
# # ----------------------------------------------------------------------------

# class AccelaScraper:
#     def __init__(self, site: str, base_url: str, module: str, store: MongoStore,
#                  permission_checker: PermissionChecker, max_pages: int = 100,
#                  delay_seconds: float = 2.0):
#         self.site = site
#         self.base_url = base_url
#         self.module = module
#         self.store = store
#         self.permission_checker = permission_checker
#         self.max_pages = max_pages
#         self.delay_seconds = delay_seconds
#         self.extractor = AccelaExtractor(site=site)

#     def run(self):
#         search_url = f"{self.base_url}?module={self.module}"

#         allowed, reason = self.permission_checker.is_allowed(search_url)
#         if not allowed:
#             log.warning("Skipping %s: %s", search_url, reason)
#             self.store.log_event(self.site, "SKIP", reason, {"url": search_url})
#             return

#         with sync_playwright() as pw:
#             browser = pw.chromium.launch(headless=HEADLESS)
#             context = browser.new_context(user_agent=USER_AGENT)
#             page = context.new_page()

#             try:
#                 self._open_search(page, search_url)
#                 self._run_general_search(page)
#                 self._paginate_and_scrape(page)
#             except Exception as e:
#                 log.exception("Fatal error scraping %s/%s", self.site, self.module)
#                 self.store.log_event(self.site, "ERROR", str(e), {"module": self.module})
#             finally:
#                 browser.close()

#     @retry(stop=stop_after_attempt(MAX_RETRIES),
#            wait=wait_exponential(multiplier=2, min=2, max=30),
#            retry=retry_if_exception_type(PWTimeout))
#     def _open_search(self, page: Page, url: str):
#         log.info("Opening %s", url)
#         page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="networkidle")

#     def _discover_search_controls(self, page: Page) -> list[dict[str, Any]]:
#         controls = page.evaluate(
#             """() => {
#                 function isVisible(el) {
#                     if (!el) return false;
#                     const style = window.getComputedStyle(el);
#                     if (style.visibility === "hidden" || style.display === "none") return false;
#                     const rect = el.getBoundingClientRect();
#                     return rect.width > 0 && rect.height > 0;
#                 }

#                 function buildXPath(el) {
#                     if (!el || el.nodeType !== 1) return "";
#                     if (el.id) return `//*[@id="${el.id}"]`;

#                     const parts = [];
#                     let node = el;
#                     while (node && node.nodeType === 1) {
#                         let ix = 1;
#                         let sib = node.previousElementSibling;
#                         while (sib) {
#                             if (sib.tagName === node.tagName) ix += 1;
#                             sib = sib.previousElementSibling;
#                         }
#                         parts.unshift(`${node.tagName.toLowerCase()}[${ix}]`);
#                         node = node.parentElement;
#                     }
#                     return "/" + parts.join("/");
#                 }

#                 function textFor(el) {
#                     const val = (el.value || "").trim();
#                     const txt = (el.innerText || el.textContent || "").trim();
#                     return val || txt;
#                 }

#                 const selectors = [
#                     "input[type='submit']",
#                     "input[type='button']",
#                     "input[value*='Search' i]",
#                     "button",
#                     "a",
#                     "[id*='Search' i]",
#                     "[title*='Search' i]",
#                 ];

#                 const seen = new Set();
#                 const candidates = [];

#                 for (const sel of selectors) {
#                     for (const el of document.querySelectorAll(sel)) {
#                         if (seen.has(el)) continue;
#                         seen.add(el);

#                         const id = el.id || "";
#                         const title = el.getAttribute("title") || "";
#                         const tag = (el.tagName || "").toLowerCase();
#                         const text = textFor(el);
#                         const hay = `${id} ${title} ${text}`.toLowerCase();
#                         if (!hay.includes("search")) continue;

#                         const visible = isVisible(el);
#                         const enabled = !el.disabled && el.getAttribute("aria-disabled") !== "true";

#                         let score = 0;
#                         if (visible) score += 100;
#                         if (enabled) score += 50;
#                         if (id.toLowerCase().includes("btnnewsearch")) score += 40;
#                         if (id.toLowerCase().includes("search")) score += 30;
#                         if (text.toLowerCase() === "search") score += 25;
#                         if (tag === "input" || tag === "button") score += 10;

#                         candidates.push({
#                             tag,
#                             id,
#                             title,
#                             text,
#                             visible,
#                             enabled,
#                             score,
#                             xpath: buildXPath(el),
#                             outer_html: (el.outerHTML || "").slice(0, 600),
#                         });
#                     }
#                 }

#                 candidates.sort((a, b) => b.score - a.score);
#                 return candidates;
#             }"""
#         )
#         return controls if isinstance(controls, list) else []

#     def _run_general_search(self, page: Page):
#         """Submits the General Search with no filters to return all records
#         for the module. SELECTOR: adjust the search-button id/text to match
#         the live page (inspect via HEADLESS=False)."""
#         candidates = self._discover_search_controls(page)
#         if not candidates:
#             log.warning("No visible search button found; assuming results are already on this page.")
#             return

#         for idx, c in enumerate(candidates[:5], start=1):
#             log.info(
#                 "Search candidate #%d score=%s visible=%s enabled=%s xpath=%s outerHTML=%s",
#                 idx,
#                 c.get("score"),
#                 c.get("visible"),
#                 c.get("enabled"),
#                 c.get("xpath"),
#                 c.get("outer_html"),
#             )

#         clicked = False
#         for c in candidates:
#             if not (c.get("visible") and c.get("enabled")):
#                 continue
#             xpath = c.get("xpath")
#             if not xpath:
#                 continue
#             try:
#                 page.locator(f"xpath={xpath}").first.click(timeout=10_000)
#                 log.info("Clicked search via xpath=%s text=%s id=%s", xpath, c.get("text"), c.get("id"))
#                 clicked = True
#                 break
#             except Exception:
#                 try:
#                     clicked_via_js = page.evaluate(
#                         """(xp) => {
#                             const node = document.evaluate(
#                                 xp,
#                                 document,
#                                 null,
#                                 XPathResult.FIRST_ORDERED_NODE_TYPE,
#                                 null
#                             ).singleNodeValue;
#                             if (!node) return false;
#                             node.click();
#                             return true;
#                         }""",
#                         xpath,
#                     )
#                     if clicked_via_js:
#                         log.info("Clicked search via JS xpath fallback=%s", xpath)
#                         clicked = True
#                         break
#                 except Exception:
#                     continue

#         if not clicked:
#             log.warning("Found search candidates but none were clickable; continuing without clicking search.")
#             return

#         page.wait_for_timeout(POST_ACTION_WAIT_MS)
#         page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)

#     def _paginate_and_scrape(self, page: Page):
#         page_num = 1
#         batch: list[dict] = []
#         total_saved = 0

#         while page_num <= self.max_pages:
#             log.info("[%s/%s] Extracting page %d", self.site, self.module, page_num)
#             extracted = self._extract_with_retry(page)
#             batch.extend(extracted.records)
#             log.info("Page %d yielded %d records (running batch=%d)",
#                       page_num, len(extracted.records), len(batch))

#             if page_num % BATCH_SAVE_EVERY_N_PAGES == 0 or not extracted.has_next:
#                 saved = self.store.upsert_records(self.site, self.module, batch)
#                 total_saved += saved
#                 log.info("Saved batch through page %d (%d upserted, %d total)",
#                          page_num, saved, total_saved)
#                 batch = []

#             if not extracted.has_next:
#                 log.info("No further pages detected. Stopping at page %d.", page_num)
#                 break

#             self._click_next(page)
#             time.sleep(self.delay_seconds)  # Rate Limit Manager: be polite
#             page_num += 1

#         if batch:
#             saved = self.store.upsert_records(self.site, self.module, batch)
#             total_saved += saved
#             log.info("Final partial batch saved (%d upserted).", saved)

#         self.store.log_event(self.site, "INFO", "scrape complete",
#                               {"module": self.module, "pages": page_num, "records_saved": total_saved})

#     @retry(stop=stop_after_attempt(MAX_RETRIES),
#            wait=wait_exponential(multiplier=2, min=2, max=20))
#     def _extract_with_retry(self, page: Page) -> ExtractedPage:
#         return self.extractor.extract(page)

#     @retry(stop=stop_after_attempt(MAX_RETRIES),
#            wait=wait_exponential(multiplier=2, min=2, max=20))
#     def _click_next(self, page: Page):
#         next_link = page.query_selector(
#             "a:has-text('Next'), a[title='Next'], a.aca_pagination_next, input[value='Next']"
#         )
#         if next_link is None:
#             raise RuntimeError("Expected a 'Next' control but found none.")
#         next_link.click()
#         page.wait_for_timeout(POST_ACTION_WAIT_MS)
#         page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)


# # ----------------------------------------------------------------------------
# # Job Manager (entry point)
# # ----------------------------------------------------------------------------

# def main():
#     parser = argparse.ArgumentParser(description="Accela CitizenAccess permit scraper")
#     parser.add_argument("--site", choices=list(SITES.keys()), default="osceola")
#     parser.add_argument("--module", default=None, help="Override module (e.g. Building, Planning)")
#     parser.add_argument("--max-pages", type=int, default=100)
#     parser.add_argument("--delay", type=float, default=2.0, help="Seconds between page requests")
#     args = parser.parse_args()

#     site_cfg = SITES[args.site]
#     modules = [args.module] if args.module else site_cfg["modules"]

#     store = MongoStore(MONGO_URI, MONGO_DB)
#     permission_checker = PermissionChecker()

#     for module in modules:
#         scraper = AccelaScraper(
#             site=args.site,
#             base_url=site_cfg["base_url"],
#             module=module,
#             store=store,
#             permission_checker=permission_checker,
#             max_pages=args.max_pages,
#             delay_seconds=args.delay,
#         )
#         scraper.run()


# if __name__ == "__main__":
#     main()


"""
Accela CitizenAccess Permit Scraper - multi-site / fan-in edition
===================================================================
Pipeline (per flowchart.mermaid), now parameterized over N sites:

  Job Manager -> [per-site: Domain Normalizer -> Robots/Permission Checker
                  -> Page Fetch Orchestrator (Playwright) -> Page Classifier
                  -> Extractor (shared or site-specific) -> Schema Normalizer]
                  ... N sites run concurrently, each on its own thread ...
                  \\_____________________  fan-in  _____________________/
                                          v
                     Single Aggregator: Dedup -> MongoDB upsert -> Logs

TARGET: Accela "Citizen Access" portals. These are public, unauthenticated
record-search portals (no login required) built on ASP.NET WebForms, so
pagination happens via __doPostBack(), not by changing the URL - hence
Playwright instead of plain requests.

WHAT CHANGED FROM THE SINGLE-SITE VERSION
------------------------------------------
1. You can now pass multiple site URLs in one run (CLI flags or a JSON file).
2. Extraction is centralized: AccelaExtractor is the shared/default extractor
   used by every site whose results grid has a "normal" Accela header/row
   structure. If a site's grid genuinely doesn't match (different vendor,
   custom-skinned instance, non-tabular layout, etc.) you register a small
   subclass for just that site - see EXTRACTOR_REGISTRY below - without
   touching the shared code path.
3. Fan-in architecture: each site runs its own Playwright browser + scraper
   in its own worker thread, and instead of writing to Mongo itself, each
   worker pushes extracted batches onto one shared queue.Queue. A single
   consumer thread ("FanInAggregator") drains that queue, does cross-batch
   dedup, and is the only thing that talks to MongoDB. That's the fan-in:
   N producers -> 1 queue -> 1 convergence point.

IMPORTANT - SELECTOR TUNING STILL REQUIRED:
Every Accela instance customizes labels/module names, and grid element IDs
are auto-generated per deployment. Verify selectors against each live site
once with HEADLESS = False before trusting a big multi-site run. Search for
"SELECTOR:" comments.

Install:
    pip install playwright pymongo tenacity
    playwright install chromium

Run (ad hoc, multiple sites on the CLI):
    python accela_permit_scraper_v2.py \\
        --url https://permits.osceola.org/CitizenAccess/Cap/CapHome.aspx --site-name osceola --module Building \\
        --url https://aca-prod.accela.com/SOMECOUNTY/Cap/CapHome.aspx     --site-name somecounty --module Building

Run (from a sites file, better for >2-3 sites):
    python accela_permit_scraper_v2.py --sites-file sites.json

sites.json format:
    [
      {"site": "osceola",    "url": "https://permits.osceola.org/CitizenAccess/Cap/CapHome.aspx", "module": "Building"},
      {"site": "somecounty", "url": "https://aca-prod.accela.com/SOMECOUNTY/Cap/CapHome.aspx",     "module": "Building"}
    ]
"""

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.robotparser as robotparser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(threadName)-14s | %(name)s | %(message)s",
)
log = logging.getLogger("accela_scraper")

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
BATCH_SAVE_EVERY_N_PAGES = 10
MAX_RETRIES = 3
HEADLESS = (os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower() in {"1", "true", "yes", "y"})
USER_AGENT = "Mozilla/5.0 (compatible; PermitResearchBot/1.0; contact=you@example.com)"
# Keep default sequential so jobs switch URL-by-URL in given order.
MAX_CONCURRENT_SITES = int(os.getenv("MAX_CONCURRENT_SITES", "1"))
DEFAULT_SITE_URLS = {
    "osceola": "https://permits.osceola.org/CitizenAccess/Cap/CapHome.aspx",
}


# ----------------------------------------------------------------------------
# Job description (one per site/module you want scraped)
# ----------------------------------------------------------------------------

@dataclass
class ScrapeJob:
    site: str          # short name, used as a Mongo collection prefix + log tag
    base_url: str      # base url for accela / full search url for arcgis
    module: str = "Building"
    max_pages: int = 100
    delay_seconds: float = 2.0
    source_type: str = "accela"  # accela | arcgis


def infer_source_type(url: str) -> str:
    u = (url or "").strip().lower()
    if "opendata.arcgis.com/search" in u or "hub.arcgis.com/search" in u:
        return "arcgis"
    return "accela"


def load_jobs(args) -> list[ScrapeJob]:
    jobs: list[ScrapeJob] = []

    if args.sites_file:
        with open(args.sites_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            jobs.append(ScrapeJob(
                site=entry["site"],
                base_url=entry["url"],
                module=entry.get("module", "Building"),
                max_pages=entry.get("max_pages", args.max_pages),
                delay_seconds=entry.get("delay", args.delay),
                source_type=entry.get("source_type", infer_source_type(entry["url"])),
            ))

    urls = args.url or []
    if urls:
        names = args.site_name or args.site or [f"site{i + 1}" for i in range(len(urls))]
        modules = args.module or ["Building"] * len(urls)
        if len(modules) == 1 and len(urls) > 1:
            modules = modules * len(urls)
        if len(names) != len(urls) or len(modules) != len(urls):
            raise ValueError(
                "--url, --site-name/--site, and --module must be given the same number of "
                f"times (got {len(urls)} urls, {len(names)} names, {len(modules)} modules)."
            )
        for name, url, module in zip(names, urls, modules):
            jobs.append(
                ScrapeJob(
                    site=name,
                    base_url=url,
                    module=module,
                    max_pages=args.max_pages,
                    delay_seconds=args.delay,
                    source_type=infer_source_type(url),
                )
            )

    # Backward-compatible mode:
    #   --site osceola --module Building --max-pages 2 --delay 2
    if not jobs and (args.site or args.site_name):
        names = args.site_name or args.site or []
        modules = args.module or ["Building"] * len(names)
        if len(modules) == 1 and len(names) > 1:
            modules = modules * len(names)
        if len(modules) != len(names):
            raise ValueError(
                "--site/--site-name and --module must be given the same number of times "
                f"(got {len(names)} names, {len(modules)} modules)."
            )
        for name, module in zip(names, modules):
            base_url = DEFAULT_SITE_URLS.get(name.strip().lower())
            if not base_url:
                raise ValueError(
                    f"No default URL mapped for site '{name}'. Use --url with --site-name, "
                    "or add this site to DEFAULT_SITE_URLS."
                )
            jobs.append(
                ScrapeJob(
                    site=name,
                    base_url=base_url,
                    module=module,
                    max_pages=args.max_pages,
                    delay_seconds=args.delay,
                    source_type="accela",
                )
            )

    if not jobs:
        raise ValueError("No jobs given. Pass --sites-file or one-or-more --url/--site-name/--module.")
    return jobs


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
    """Checks robots.txt before we touch a domain. Shared across all site
    threads (safe: dict-per-domain cache, no cross-domain mutation), so each
    domain's robots.txt is only fetched once even in a multi-site run."""

    def __init__(self):
        self._cache: dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._lock = threading.Lock()

    def _get_parser(self, domain: str) -> Optional[robotparser.RobotFileParser]:
        with self._lock:
            if domain in self._cache:
                return self._cache[domain]
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(domain, "/robots.txt"))
        try:
            rp.read()
        except Exception as e:
            log.warning("Could not read robots.txt for %s (%s); assuming allowed.", domain, e)
            rp = None
        with self._lock:
            self._cache[domain] = rp
        return rp

    def is_allowed(self, url: str, user_agent: str = USER_AGENT) -> tuple[bool, str]:
        domain = normalize_domain(url)
        rp = self._get_parser(domain)
        if rp is None:
            return True, "robots.txt unavailable, defaulting to allow"
        allowed = rp.can_fetch(user_agent, url)
        reason = "allowed by robots.txt" if allowed else "disallowed by robots.txt"
        return allowed, reason


# ----------------------------------------------------------------------------
# MongoDB storage (Schema Normalizer output target). This is the ONLY thing
# that talks to Mongo now - the FanInAggregator owns the one MongoStore
# instance and every site thread reaches it only via the queue.
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
        coll.create_index("_dedup_key", unique=True, sparse=True)
        ops = []
        for rec in records:
            key = rec.get("record_number")
            dedup_field = "record_number"
            if not key:
                key = rec.get("_dedup_key")
                dedup_field = "_dedup_key"
            if not key:
                continue
            rec["scraped_at"] = dt.datetime.utcnow()
            ops.append(UpdateOne({dedup_field: key}, {"$set": rec}, upsert=True))
        if not ops:
            return 0
        try:
            result = coll.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except PyMongoError as e:
            log.error("Mongo bulk_write failed for %s/%s: %s", site, module, e)
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
# Page Classifier + Extractor
#
# AccelaExtractor is the CENTRALIZED / SHARED extractor. Most Accela
# CitizenAccess deployments render the same grid markup (table with
# gdvPermitList-style id or ACA_Grid class, ACA_TabRow_Odd/Even rows), just
# with different header *labels*. HEADER_ALIASES absorbs that variance so one
# function handles every "normal" site. Give a per-site alias override via
# SITE_HEADER_ALIASES if a county just renames columns.
#
# Only fall back to a dedicated subclass (see EXTRACTOR_REGISTRY) when a
# site's markup structurally differs - e.g. it's not a <table> grid at all,
# or pagination isn't a "Next" link.
# ----------------------------------------------------------------------------

@dataclass
class ExtractedPage:
    records: list[dict] = field(default_factory=list)
    has_next: bool = False


class AccelaExtractor:
    """Shared extractor for standard Accela CitizenAccess results grids."""

    HEADER_ALIASES = {
        "record_number": {"record number", "permit number", "record #", "permit #", "application number"},
        "record_type": {"record type", "permit type", "type"},
        "project_name": {"project name", "project"},
        "address": {"address", "site address", "property address"},
        "status": {"status"},
        "action": {"action"},
        "description": {"description", "work description", "scope of work"},
        "issue_date": {"opened date", "issue date", "date", "filed date"},
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
    def _norm_label(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").strip().lower()).strip()

    @classmethod
    def _build_header_lookup(cls, site: str) -> dict[str, str]:
        merged: dict[str, set[str]] = {k: set(v) for k, v in cls.HEADER_ALIASES.items()}
        for key, aliases in cls.SITE_HEADER_ALIASES.get(site, {}).items():
            merged.setdefault(key, set()).update(aliases)
        lookup: dict[str, str] = {}
        for canonical, aliases in merged.items():
            lookup[cls._norm_label(canonical)] = canonical
            for alias in aliases:
                lookup[cls._norm_label(alias)] = canonical
        return lookup

    def _normalize_key(self, header_text: str) -> str:
        norm = self._norm_label(header_text)
        if norm in self._header_lookup:
            return self._header_lookup[norm]
        return re.sub(r"[^a-z0-9]+", "_", norm).strip("_")

    @staticmethod
    def _is_pagination_token(value: str) -> bool:
        token = (value or "").strip().lower()
        if not token:
            return True
        if token in {"< prev", "prev", "next >", "next", "..."}:
            return True
        if token.isdigit():
            return True
        return False

    @classmethod
    def _is_pagination_row(cls, values: list[str]) -> bool:
        compact = " ".join(values).strip().lower()
        if "prev" in compact and "next" in compact:
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
            return text, href
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
        if headers and len(headers) == len(values):
            for key, value in zip(headers, values):
                if key:
                    rec[key] = value
            return rec

        # Fallback when the row has leading checkbox/extra cells.
        start_idx = 1 if values and not values[0].strip() else 0
        trimmed = values[start_idx:]
        for idx, key in enumerate(cls.PREFERRED_COLUMNS):
            if idx >= len(trimmed):
                break
            rec[key] = trimmed[idx]

        for key, value in zip(headers, values):
            if key and key in cls.PREFERRED_COLUMNS and key not in rec:
                rec[key] = value
        return rec

    def extract(self, page: Page) -> ExtractedPage:
        # SELECTOR: standard Accela grid id/class patterns, with a
        # "biggest table on the page" fallback.
        table = (
            page.query_selector("table[id*='gdvPermitList']")
            or page.query_selector("table.ACA_Grid")
            or self._largest_data_table(page)
        )
        if table is None:
            return ExtractedPage(records=[], has_next=False)

        header_els = table.query_selector_all("thead th, tr:first-child th")
        raw_headers = [(h.inner_text() or "").strip() for h in header_els]
        headers = [self._normalize_key(h) for h in raw_headers]

        rows = table.query_selector_all("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")
        if not rows:
            rows = table.query_selector_all("tbody tr, tr:not(:first-child)")

        records = []
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells:
                continue
            values = [c.inner_text().strip() for c in cells]
            if self._is_pagination_row(values):
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

            if not rec.get("record_number"):
                continue
            if self._is_pagination_token(str(rec.get("record_number"))):
                continue

            if any(rec.values()):
                records.append(rec)

        return ExtractedPage(records=records, has_next=self._has_next_page(page))

    def _largest_data_table(self, page: Page):
        tables = page.query_selector_all("table")
        best, best_rows = None, 0
        for t in tables:
            n = len(t.query_selector_all("tr"))
            if n > best_rows:
                best, best_rows = t, n
        return best if best_rows > 1 else None

    def _has_next_page(self, page: Page) -> bool:
        next_link = page.query_selector(
            "a:has-text('Next'), a[title='Next'], a.aca_pagination_next, input[value='Next']"
        )
        if next_link is None:
            return False
        disabled = next_link.get_attribute("disabled")
        classes = next_link.get_attribute("class") or ""
        return disabled is None and "disabled" not in classes


# ----------------------------------------------------------------------------
# Extractor registry: this is the "same structure -> shared function, else
# per-site function" switch you asked for. Default is the shared
# AccelaExtractor above. Register a subclass keyed by exact site name only
# for sites whose grid genuinely doesn't fit the shared shape.
# ----------------------------------------------------------------------------

EXTRACTOR_REGISTRY: dict[str, type] = {}


def register_extractor(site_name: str):
    """Decorator: @register_extractor('somecounty') on a subclass of
    AccelaExtractor to override extraction for just that one site name."""
    def deco(cls):
        EXTRACTOR_REGISTRY[site_name.strip().lower()] = cls
        return cls
    return deco


def resolve_extractor(site: str) -> AccelaExtractor:
    cls = EXTRACTOR_REGISTRY.get(site.strip().lower(), AccelaExtractor)
    return cls(site=site)


# Example of the "different structure -> its own function" escape hatch.
# Leave unregistered sites on the shared AccelaExtractor; only add one of
# these when you've actually confirmed (HEADLESS=False) that a site's grid
# doesn't match the shared selectors/aliases above.
#
# @register_extractor("somecounty")
# class SomeCountyExtractor(AccelaExtractor):
#     def extract(self, page: Page) -> ExtractedPage:
#         # e.g. this deployment renders results as <div> cards, not a <table>
#         ...


# ----------------------------------------------------------------------------
# Fan-in aggregator: the single convergence point every site thread feeds.
# ----------------------------------------------------------------------------

class FanInAggregator:
    """N producer threads (one per ScrapeJob) push (site, module, records)
    batches onto self.queue. This single consumer drains the queue, dedups
    across the whole run (so re-fetched pages across retries don't double
    count), and is the only code path that writes to MongoDB."""

    _SENTINEL = object()

    def __init__(self, store: MongoStore):
        self.store = store
        self.queue: "queue.Queue" = queue.Queue()
        self._seen: set[tuple[str, str, str]] = set()
        self.total_upserted = 0

    def put(self, site: str, module: str, records: list[dict]):
        self.queue.put((site, module, records))

    def signal_done(self):
        self.queue.put(self._SENTINEL)

    def run(self):
        """Runs in its own thread; call signal_done() once per producer,
        then join the aggregator thread after all producers finish."""
        pending_sentinels = 0
        while True:
            item = self.queue.get()
            if item is self._SENTINEL:
                pending_sentinels += 1
                continue
            site, module, records = item
            fresh = []
            for rec in records:
                dedup = rec.get("record_number") or rec.get("_dedup_key") or rec.get("detail_url")
                key = (site, module, str(dedup))
                if key in self._seen:
                    continue
                self._seen.add(key)
                fresh.append(rec)
            saved = self.store.upsert_records(site, module, fresh)
            self.total_upserted += saved
            log.info("[fan-in] %s/%s: +%d new of %d received (upserted=%d, run total=%d)",
                      site, module, len(fresh), len(records), saved, self.total_upserted)
            if pending_sentinels >= self._expected_producers and self.queue.empty():
                break

    # set by run_all() before starting the aggregator thread
    _expected_producers = 0


# ----------------------------------------------------------------------------
# Page Fetch Orchestrator + Rate Limit Manager + Failure Handler/Retry
# (one instance per ScrapeJob / worker thread; writes go through the
# aggregator's queue instead of touching Mongo directly)
# ----------------------------------------------------------------------------

class AccelaScraper:
    def __init__(self, job: ScrapeJob, aggregator: FanInAggregator,
                 permission_checker: PermissionChecker):
        self.job = job
        self.aggregator = aggregator
        self.permission_checker = permission_checker
        self.extractor = resolve_extractor(job.site)

    def run(self):
        job = self.job
        parsed = urlparse(job.base_url)
        qs = parse_qs(parsed.query or "")
        if "module" in qs:
            search_url = job.base_url
        else:
            sep = "&" if "?" in job.base_url else "?"
            search_url = f"{job.base_url}{sep}module={job.module}"
        log.info(
            "[%s] START url=%s module=%s max_pages=%d delay=%.2fs",
            job.site, job.base_url, job.module, job.max_pages, job.delay_seconds
        )

        allowed, reason = self.permission_checker.is_allowed(search_url)
        if not allowed:
            log.warning("Skipping %s: %s", search_url, reason)
            self.aggregator.store.log_event(job.site, "SKIP", reason, {"url": search_url})
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
                log.exception("Fatal error scraping %s/%s", job.site, job.module)
                self.aggregator.store.log_event(job.site, "ERROR", str(e), {"module": job.module})
            finally:
                browser.close()
                log.info("[%s] END module=%s", job.site, job.module)

    @retry(stop=stop_after_attempt(MAX_RETRIES),
           wait=wait_exponential(multiplier=2, min=2, max=30),
           retry=retry_if_exception_type(PWTimeout))
    def _open_search(self, page: Page, url: str):
        log.info("Opening %s", url)
        page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="networkidle")

    def _run_general_search(self, page: Page):
        """Submits the General Search with no filters to return all records
        for the module. SELECTOR: verify per-site with HEADLESS=False."""
        selectors = [
            "#ctl00_PlaceHolderMain_btnNewSearch",
            "input[value='Search']",
            "a:has-text('Search')",
        ]
        clicked = False
        for sel in selectors:
            locator = page.locator(sel)
            count = locator.count()
            if count == 0:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if candidate.is_visible() and candidate.is_enabled():
                        candidate.click(timeout=10_000)
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            log.warning("[%s] No visible search button found; assuming results are already on this page.", self.job.site)
            return

        page.wait_for_timeout(POST_ACTION_WAIT_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)

    def _paginate_and_scrape(self, page: Page):
        job = self.job
        page_num = 1
        batch: list[dict] = []
        batch_start_page = 1

        while page_num <= job.max_pages:
            log.info("[%s/%s] Extracting page %d", job.site, job.module, page_num)
            extracted = self._extract_with_retry(page)
            batch.extend(extracted.records)
            log.info("[%s] Page %d yielded %d records (running batch=%d)",
                     job.site, page_num, len(extracted.records), len(batch))

            if page_num % BATCH_SAVE_EVERY_N_PAGES == 0 or not extracted.has_next:
                log.info(
                    "[%s] Queueing batch pages=%d-%d records=%d",
                    job.site, batch_start_page, page_num, len(batch)
                )
                self.aggregator.put(job.site, job.module, batch)
                batch = []
                batch_start_page = page_num + 1

            if not extracted.has_next:
                log.info("[%s] No further pages detected. Stopping at page %d.", job.site, page_num)
                break

            self._click_next(page)
            time.sleep(job.delay_seconds)  # Rate Limit Manager: be polite
            page_num += 1

        if batch:
            log.info(
                "[%s] Queueing final partial batch pages=%d-%d records=%d",
                job.site, batch_start_page, page_num, len(batch)
            )
            self.aggregator.put(job.site, job.module, batch)

        self.aggregator.store.log_event(
            job.site, "INFO", "scrape complete",
            {"module": job.module, "pages": page_num},
        )

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


class ArcGISScraper:
    """Playwright scraper for ArcGIS Hub search result pages."""

    def __init__(self, job: ScrapeJob, aggregator: FanInAggregator, permission_checker: PermissionChecker):
        self.job = job
        self.aggregator = aggregator
        self.permission_checker = permission_checker

    @staticmethod
    def _make_dedup_key(url: str, title: str) -> str:
        payload = f"{url}|{title}".encode("utf-8", errors="ignore")
        return hashlib.sha1(payload).hexdigest()

    def _extract_cards(self, page: Page) -> list[dict[str, Any]]:
        rows = page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const cards = document.querySelectorAll("article, li, div.card, .search-result");
                for (const card of cards) {
                    const a = card.querySelector("a[href]");
                    if (!a) continue;
                    const href = (a.getAttribute("href") || "").trim();
                    if (!href) continue;
                    const abs = new URL(href, window.location.href).toString();
                    const title = (a.textContent || "").trim();
                    if (!title || seen.has(abs)) continue;
                    seen.add(abs);
                    const descEl = card.querySelector("p, .description, .result-description");
                    const typeEl = card.querySelector(".type, .result-type, [data-item-type]");
                    out.push({
                        title,
                        detail_url: abs,
                        description: (descEl && descEl.textContent ? descEl.textContent : "").trim(),
                        record_type: (typeEl && typeEl.textContent ? typeEl.textContent : "ArcGIS Dataset").trim(),
                    });
                }
                return out;
            }"""
        )
        if not isinstance(rows, list):
            return []
        docs: list[dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            url = str(r.get("detail_url") or "").strip()
            title = str(r.get("title") or "").strip()
            if not url and not title:
                continue
            docs.append(
                {
                    "_dedup_key": self._make_dedup_key(url, title),
                    "record_number": None,
                    "record_type": r.get("record_type") or "ArcGIS Dataset",
                    "project_name": title,
                    "description": r.get("description"),
                    "detail_url": url,
                    "source": "arcgis",
                }
            )
        return docs

    def _goto_next_page(self, page: Page) -> bool:
        selectors = [
            "button[aria-label*='Next' i]",
            "a[aria-label*='Next' i]",
            "button:has-text('Next')",
            "a:has-text('Next')",
        ]
        for sel in selectors:
            loc = page.locator(sel)
            count = loc.count()
            if count == 0:
                continue
            for idx in range(count):
                b = loc.nth(idx)
                try:
                    if b.is_visible() and b.is_enabled():
                        b.click(timeout=10_000)
                        page.wait_for_timeout(1200)
                        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)
                        return True
                except Exception:
                    continue
        return False

    def run(self):
        job = self.job
        log.info("[%s] START (arcgis) url=%s max_pages=%d", job.site, job.base_url, job.max_pages)
        allowed, reason = self.permission_checker.is_allowed(job.base_url)
        if not allowed:
            log.warning("Skipping %s: %s", job.base_url, reason)
            self.aggregator.store.log_event(job.site, "SKIP", reason, {"url": job.base_url, "source": "arcgis"})
            return

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=HEADLESS)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            batch: list[dict[str, Any]] = []
            batch_start_page = 1
            try:
                page.goto(job.base_url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="networkidle")
                for page_num in range(1, job.max_pages + 1):
                    records = self._extract_cards(page)
                    batch.extend(records)
                    log.info("[%s/arcgis] page=%d found=%d running_batch=%d", job.site, page_num, len(records), len(batch))

                    if page_num % BATCH_SAVE_EVERY_N_PAGES == 0:
                        log.info("[%s] Queueing batch pages=%d-%d records=%d", job.site, batch_start_page, page_num, len(batch))
                        self.aggregator.put(job.site, job.module, batch)
                        batch = []
                        batch_start_page = page_num + 1

                    if page_num >= job.max_pages:
                        break
                    if not self._goto_next_page(page):
                        log.info("[%s] ArcGIS no next page after page=%d", job.site, page_num)
                        break
                    time.sleep(job.delay_seconds)

                if batch:
                    log.info("[%s] Queueing final partial batch pages=%d-%d records=%d", job.site, batch_start_page, job.max_pages, len(batch))
                    self.aggregator.put(job.site, job.module, batch)

                self.aggregator.store.log_event(
                    job.site, "INFO", "arcgis scrape complete",
                    {"module": job.module, "pages": job.max_pages, "source": "arcgis"},
                )
            except Exception as e:
                log.exception("Fatal error scraping arcgis site=%s", job.site)
                self.aggregator.store.log_event(job.site, "ERROR", str(e), {"module": job.module, "source": "arcgis"})
            finally:
                browser.close()
                log.info("[%s] END (arcgis)", job.site)


# ----------------------------------------------------------------------------
# Job Manager (entry point): fans OUT one thread per site job, fans IN
# through a single aggregator thread.
# ----------------------------------------------------------------------------

def run_all(jobs: list[ScrapeJob]):
    store = MongoStore(MONGO_URI, MONGO_DB)
    permission_checker = PermissionChecker()
    aggregator = FanInAggregator(store)
    aggregator._expected_producers = len(jobs)
    log.info("Run mode: max_concurrent_sites=%d batch_save_every_n_pages=%d", MAX_CONCURRENT_SITES, BATCH_SAVE_EVERY_N_PAGES)

    agg_thread = threading.Thread(target=aggregator.run, name="fan-in-writer", daemon=False)
    agg_thread.start()

    def _worker(job: ScrapeJob):
        log.info("[job] start site=%s source=%s url=%s module=%s max_pages=%d", job.site, job.source_type, job.base_url, job.module, job.max_pages)
        try:
            if job.source_type == "arcgis":
                ArcGISScraper(job, aggregator, permission_checker).run()
            else:
                AccelaScraper(job, aggregator, permission_checker).run()
        finally:
            aggregator.signal_done()
            log.info("[job] done site=%s module=%s", job.site, job.module)

    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_SITES, len(jobs)),
                             thread_name_prefix="site") as pool:
        futures = {pool.submit(_worker, job): job for job in jobs}
        for fut in futures:
            fut.result()  # surface any exception from a worker

    agg_thread.join()
    log.info("All sites complete. Total records upserted this run: %d", aggregator.total_upserted)


def main():
    parser = argparse.ArgumentParser(description="Accela CitizenAccess permit scraper (multi-site, fan-in)")
    parser.add_argument("--sites-file", help="JSON file: list of {site,url,module,max_pages,delay}")
    parser.add_argument("--url", action="append", help="Base CapHome.aspx URL; repeat per site")
    parser.add_argument("--site-name", action="append", help="Short name per --url, same order")
    parser.add_argument("--site", action="append", help="Alias of --site-name (backward compatibility)")
    parser.add_argument("--module", action="append", help="Module per --url, same order (e.g. Building)")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between page requests")
    args = parser.parse_args()

    jobs = load_jobs(args)
    log.info("Loaded %d scrape job(s): %s", len(jobs), [(j.site, j.module) for j in jobs])
    run_all(jobs)


if __name__ == "__main__":
    main()
