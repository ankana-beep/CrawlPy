"""Building permit objective extraction, cleaning, and standardization."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from scraper_framework.smart_crawler.models import ExtractedPage


OBJECTIVE_NAME = "building_permits"
LEGACY_OBJECTIVE_NAMES = {"residential_building_permits"}

PERMIT_KEYWORDS = (
    "permit",
    "permits",
    "building permit",
    "residential permit",
    "commercial permit",
    "construction permit",
    "electrical permit",
    "mechanical permit",
    "plumbing permit",
    "roofing permit",
    "demolition permit",
    "trade permit",
    "fire permit",
    "zoning permit",
    "development permit",
    "inspection",
    "inspections",
    "contractor",
    "parcel",
    "valuation",
    "accela",
    "energov",
    "cityview",
    "epermits",
    "permit search",
    "permit portal",
)

RESIDENTIAL_KEYWORDS = (
    "residential",
    "single family",
    "single-family",
    "duplex",
    "townhome",
    "townhouse",
    "dwelling",
    "home",
    "garage",
    "addition",
    "remodel",
    "roof",
    "solar",
)

PERMIT_CATEGORY_KEYWORDS = {
    "residential": RESIDENTIAL_KEYWORDS,
    "commercial": ("commercial", "tenant improvement", "tenant buildout", "retail", "office", "industrial"),
    "electrical": ("electrical", "electric", "service upgrade", "panel", "wiring"),
    "mechanical": ("mechanical", "hvac", "air conditioning", "furnace", "duct"),
    "plumbing": ("plumbing", "sewer", "water heater", "gas line", "backflow"),
    "roofing": ("roof", "reroof", "roofing"),
    "solar": ("solar", "photovoltaic", "pv"),
    "demolition": ("demolition", "demo", "wrecking"),
    "fire": ("fire", "sprinkler", "alarm"),
    "pool": ("pool", "spa"),
    "zoning": ("zoning", "land use", "variance"),
}

FIELD_ALIASES = {
    "permit_number": ("permit no", "permit number", "permit #", "record number", "case number"),
    "permit_type": ("type", "permit type", "record type", "work class", "work type"),
    "status": ("status", "permit status", "record status"),
    "application_date": ("application date", "applied", "applied date", "filed", "submitted"),
    "issued_date": ("issued", "issue date", "issued date"),
    "final_date": ("final", "finaled", "closed", "completed", "expiration date"),
    "address": ("address", "site address", "project address", "location"),
    "parcel_number": ("parcel", "parcel number", "apn", "folio", "tax id"),
    "contractor": ("contractor", "licensee", "builder"),
    "owner": ("owner", "applicant", "property owner"),
    "valuation": ("valuation", "job value", "project value", "estimated cost"),
    "square_feet": ("square feet", "sq ft", "sqft", "area"),
    "description": ("description", "scope", "work description", "project description"),
    "county": ("county",),
    "state": ("state",),
    "jurisdiction": ("jurisdiction", "city", "agency", "municipality"),
}

PERMIT_NUMBER_RE = re.compile(r"\b(?:permit|record|case)\s*(?:number|no\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9.-]{4,})\b", re.I)
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
MONEY_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?")


class PermitObjectiveExtractor:
    def score_url(self, url: str) -> int:
        text = url.lower()
        score = sum(5 for word in PERMIT_KEYWORDS if word.replace(" ", "") in text.replace("-", "").replace("_", ""))
        score += sum(3 for word in RESIDENTIAL_KEYWORDS if word.replace(" ", "") in text.replace("-", "").replace("_", ""))
        return score

    def score_page(self, extracted: ExtractedPage) -> int:
        text = " ".join([extracted.title or "", extracted.text[:10000] or ""]).lower()
        score = sum(4 for word in PERMIT_KEYWORDS if word in text)
        score += sum(3 for word in RESIDENTIAL_KEYWORDS if word in text)
        score += len(extracted.forms) * 2
        score += len([table for table in extracted.tables if _table_mentions_permit(table)]) * 5
        return score

    def prioritize_urls(self, urls: Iterable[str]) -> Dict[str, int]:
        return {url: self.score_url(url) for url in urls}

    def extract_page_records(self, extracted: ExtractedPage, *, run_id: str, source_url: str) -> Dict[str, Any]:
        score = self.score_page(extracted)
        records: List[Dict[str, Any]] = []
        records.extend(self._records_from_tables(extracted, run_id=run_id, source_url=source_url))
        records.extend(self._records_from_json(extracted.embedded_json, run_id=run_id, source_url=source_url))

        if not records and score > 0:
            text_record = self._record_from_text(extracted.text, run_id=run_id, source_url=source_url)
            if text_record:
                records.append(text_record)

        return {
            "name": OBJECTIVE_NAME,
            "score": score,
            "is_relevant": score >= 8 or bool(records),
            "standardized_records": records,
            "record_count": len(records),
        }

    def extract_payload_records(self, payload: Any, *, run_id: str, source_url: str) -> Dict[str, Any]:
        records = self._records_from_any(payload, run_id=run_id, source_url=source_url)
        score = 10 if records else self.score_url(source_url)
        return {
            "name": OBJECTIVE_NAME,
            "score": score,
            "is_relevant": score >= 8 or bool(records),
            "standardized_records": records,
            "record_count": len(records),
        }

    def _records_from_tables(self, extracted: ExtractedPage, *, run_id: str, source_url: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for table in extracted.tables:
            rows = table.get("rows") or []
            if len(rows) < 2:
                continue
            headers = [_norm_header(value) for value in rows[0]]
            mapped = [_field_for_header(header) for header in headers]
            if not any(mapped):
                continue
            for row in rows[1:]:
                raw = {headers[index]: row[index] for index in range(min(len(headers), len(row)))}
                record = {field: row[index] for index, field in enumerate(mapped) if field and index < len(row)}
                standardized = self._standardize(record, run_id=run_id, source_url=source_url, raw=raw)
                if _has_permit_signal(standardized):
                    out.append(standardized)
        return out

    def _records_from_json(self, embedded_json: List[Dict[str, Any]], *, run_id: str, source_url: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in embedded_json:
            out.extend(self._records_from_any(item.get("data"), run_id=run_id, source_url=source_url))
        return out

    def _records_from_any(self, value: Any, *, run_id: str, source_url: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for obj in _walk_dicts(value):
            record: Dict[str, Any] = {}
            for key, item_value in obj.items():
                field = _field_for_header(_norm_header(str(key)))
                if field:
                    record[field] = item_value
            if record:
                standardized = self._standardize(record, run_id=run_id, source_url=source_url, raw=obj)
                if _has_permit_signal(standardized):
                    out.append(standardized)
        return _dedupe_records(out)

    def _record_from_text(self, text: str, *, run_id: str, source_url: str) -> Optional[Dict[str, Any]]:
        permit_match = PERMIT_NUMBER_RE.search(text)
        date_match = DATE_RE.search(text)
        money_match = MONEY_RE.search(text)
        record = {
            "permit_number": permit_match.group(1) if permit_match else None,
            "application_date": date_match.group(0) if date_match else None,
            "valuation": money_match.group(0) if money_match else None,
            "description": text[:1000],
        }
        standardized = self._standardize(record, run_id=run_id, source_url=source_url, raw={"text_excerpt": text[:5000]})
        return standardized if _has_permit_signal(standardized) else None

    def _standardize(self, record: Dict[str, Any], *, run_id: str, source_url: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {key: _clean_value(value) for key, value in record.items() if _clean_value(value) not in {None, ""}}
        permit_type = str(cleaned.get("permit_type") or "")
        description = str(cleaned.get("description") or "")
        category_text = " ".join([permit_type, description, source_url])
        cleaned.setdefault("permit_category", _permit_category(category_text))
        cleaned.setdefault("is_residential", _mentions_any(category_text, RESIDENTIAL_KEYWORDS))
        cleaned.setdefault("source_url", source_url)
        cleaned.setdefault("source_domain", urlparse(source_url).netloc)
        cleaned.setdefault("run_id", run_id)
        cleaned.setdefault("objective", OBJECTIVE_NAME)
        cleaned.setdefault("raw", raw)
        cleaned.setdefault("extracted_at", datetime.now(timezone.utc))
        cleaned.setdefault("confidence", _confidence(cleaned))
        cleaned["record_key"] = _record_key(source_url, cleaned)
        cleaned["record_fingerprint"] = _record_fingerprint(cleaned)
        return cleaned


def _norm_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip().lower()


def _field_for_header(header: str) -> Optional[str]:
    for field, aliases in FIELD_ALIASES.items():
        if header in aliases:
            return field
    if header == "permit":
        return "permit_number"
    if header == "type":
        return "permit_type"
    if header == "date":
        return "application_date"
    for field, aliases in FIELD_ALIASES.items():
        if any(alias in header for alias in aliases if len(alias) > 4):
            return field
    return None


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        if MONEY_RE.fullmatch(cleaned):
            return float(cleaned.replace("$", "").replace(",", "").strip())
        return cleaned
    return value


def _walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _table_mentions_permit(table: Dict[str, Any]) -> bool:
    text = " ".join(" ".join(str(cell) for cell in row) for row in table.get("rows", [])[:3]).lower()
    return _mentions_any(text, PERMIT_KEYWORDS)


def _mentions_any(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _has_permit_signal(record: Dict[str, Any]) -> bool:
    return bool(record.get("permit_number") or record.get("permit_type") or record.get("address") or record.get("parcel_number"))


def _confidence(record: Dict[str, Any]) -> float:
    score = 0.25
    for field in ("permit_number", "permit_type", "status", "address", "parcel_number", "issued_date", "application_date"):
        if record.get(field):
            score += 0.1
    if record.get("is_residential"):
        score += 0.1
    return min(round(score, 2), 0.95)


def _permit_category(text: str) -> str:
    for category, keywords in PERMIT_CATEGORY_KEYWORDS.items():
        if _mentions_any(text, keywords):
            return category
    return "general"


def _record_key(source_url: str, record: Dict[str, Any]) -> str:
    identity = "|".join(
        str(record.get(field) or "")
        for field in ("permit_number", "address", "parcel_number", "permit_type")
    )
    raw = f"{urlparse(source_url).netloc}:{identity or record.get('description', '')[:200]}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _record_fingerprint(record: Dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in record.items()
        if key
        not in {
            "run_id",
            "source_url",
            "source_domain",
            "raw",
            "extracted_at",
            "record_key",
            "record_fingerprint",
        }
    }
    raw = json.dumps(comparable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for record in records:
        identity = (record["record_key"], record["record_fingerprint"])
        if identity not in seen:
            seen.add(identity)
            out.append(record)
    return out
