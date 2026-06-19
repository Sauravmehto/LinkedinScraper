"""Map PersonCandidate + company context to HubSpot import template columns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from gtm.linkedin_scraper.hubspot_sync.mapper import CompanyRow, split_person_name
from gtm.linkedin_scraper.people_discovery.candidate_extract import normalize_profile_url
from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

from .company_lookup import CompanyIndexes, build_company_indexes, lookup_company


def _normalize_header(header: str) -> str:
    return (header or "").strip().casefold()


def _normalize_website(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    return text


def _city_from_headquarters(headquarters: str) -> str:
    text = (headquarters or "").strip()
    if not text:
        return ""
    if "," in text:
        return text.split(",", 1)[0].strip()
    return text


def _state_from_headquarters(headquarters: str) -> str:
    text = (headquarters or "").strip()
    if "," not in text:
        return ""
    return text.split(",", 1)[1].strip()


def _is_linkedin_slug_id(token: str) -> bool:
    """True when a slug segment looks like a LinkedIn ID suffix, not a real name."""
    t = (token or "").strip().lower()
    if not t:
        return False
    if any(c.isdigit() for c in t):
        return True
    return len(t) >= 8


def _linkedin_slug_tail(linkedin_url: str) -> str:
    url = normalize_profile_url(linkedin_url)
    if not url or "/in/" not in url.lower():
        return ""
    slug = url.rstrip("/").split("/")[-1].lower()
    parts = [p for p in slug.split("-") if p]
    if len(parts) < 3:
        return ""
    tail = parts[-1]
    return tail if _is_linkedin_slug_id(tail) else ""


def _clean_last_name(last: str, linkedin_url: str = "") -> str:
    """Strip trailing numeric IDs and LinkedIn slug suffixes from last names."""
    text = re.sub(r"(\s+\d+)+$", "", (last or "").strip()).strip()
    if not text:
        return ""

    slug_tail = _linkedin_slug_tail(linkedin_url)
    if not slug_tail:
        return text

    parts = text.split()
    if parts and parts[-1].lower() == slug_tail:
        return " ".join(parts[:-1]).strip()
    return text


@dataclass(frozen=True)
class ReportDefaults:
    lead_status: str = ""
    lifecycle_stage: str = "lead"
    owner_id: str = ""


def _value_for_header(
    header_key: str,
    candidate: PersonCandidate,
    company: CompanyRow | None,
    defaults: ReportDefaults,
) -> Any:
    first, last = split_person_name(candidate.person_name)
    person_li = normalize_profile_url(candidate.linkedin_in_url)
    last = _clean_last_name(last, person_li)
    title = (candidate.person_title or candidate.role_target or "").strip()
    email = (
        (candidate.work_email or candidate.personal_email or "").strip().lower()
    )
    mobile = (candidate.direct_dial or candidate.hq_phone or "").strip()
    phone_fallback = mobile
    company_li = normalize_profile_url(candidate.company_linkedin)
    website = _normalize_website(candidate.company_website)
    city = (candidate.city or "").strip()
    state = (candidate.state or "").strip()
    country = (candidate.country or "").strip()
    aum = ""
    asset_focus = ""
    if company:
        if not city:
            city = _city_from_headquarters(company.headquarters)
        if not state:
            state = _state_from_headquarters(company.headquarters)
        if not country:
            country = (company.country or "").strip()
        aum = (company.aum or "").strip()
        asset_focus = (company.asset_type or "").strip()

    score_text = f"Score: {candidate.score} ({candidate.confidence})"
    role_target = (candidate.role_target or "").strip()

    mapping: dict[str, Any] = {
        "first name": first,
        "last name": last,
        "email": email,
        "job title": title,
        "company name": (candidate.company_name or "").strip(),
        "website url": website,
        "linkedin account": person_li,
        "linkedin company page": company_li,
        "mobile phone number": mobile,
        "phone": phone_fallback,
        "phone number": phone_fallback,
        "lead status": defaults.lead_status,
        "lifecycle stage": defaults.lifecycle_stage,
        "contact owner": defaults.owner_id,
        "communication owner": defaults.owner_id,
        "associated note": "",
        "country": country,
        "country/region": country,
        "region": state,
        "state/region": "",
        "city": city,
        "score": score_text,
        "role target": role_target,
        "source": (candidate.source or "").strip(),
        "aum": aum,
        "asset focus": asset_focus,
        "persona": "",
        "record id": "",
        "create date": "",
        "last activity": "",
        "first conversion date": "",
        "next outreach date": "",
    }
    return mapping.get(header_key, "")


def build_row_values(
    headers: list[Any],
    candidate: PersonCandidate,
    *,
    company: CompanyRow | None = None,
    defaults: ReportDefaults | None = None,
) -> list[Any]:
    """Return one cell value per template header (row 1 order)."""
    cfg = defaults or ReportDefaults()
    out: list[Any] = []

    for raw_header in headers:
        header = str(raw_header or "").strip()
        key = _normalize_header(header)
        out.append(_value_for_header(key, candidate, company, cfg))
    return out


def resolve_company_for_candidate(
    candidate: PersonCandidate,
    companies_by_name: dict[str, CompanyRow],
    *,
    indexes: CompanyIndexes | None = None,
) -> CompanyRow | None:
    idx = indexes or build_company_indexes(list(companies_by_name.values()))
    return lookup_company(
        company_name=candidate.company_name,
        company_website=candidate.company_website,
        company_linkedin=candidate.company_linkedin,
        indexes=idx,
    )
