"""Map PersonCandidate + company context to HubSpot import template columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gtm.linkedin_scraper.hubspot_sync.mapper import CompanyRow, contact_import_note, split_person_name
from gtm.linkedin_scraper.people_discovery.candidate_extract import normalize_profile_url
from gtm.linkedin_scraper.people_discovery.types import PersonCandidate


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


def _build_associated_note(
    candidate: PersonCandidate,
    company: CompanyRow | None,
) -> str:
    parts = [contact_import_note(candidate)]
    if candidate.company_type and candidate.company_type != "UNKNOWN":
        parts.append(f"Company type: {candidate.company_type}")
    if candidate.notes:
        parts.append(f"Notes: {candidate.notes}")
    if company:
        if company.country:
            parts.append(f"Country: {company.country}")
        if company.aum:
            parts.append(f"AUM: {company.aum}")
        if company.asset_type:
            parts.append(f"Asset focus: {company.asset_type}")
    return "\n".join(parts)[:65535]


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
    title = (candidate.person_title or candidate.role_target or "").strip()
    email = (candidate.work_email or "").strip().lower()
    mobile = (candidate.direct_dial or candidate.hq_phone or "").strip()
    phone_fallback = mobile
    person_li = normalize_profile_url(candidate.linkedin_in_url)
    company_li = normalize_profile_url(candidate.company_linkedin)
    website = _normalize_website(candidate.company_website)
    city = (candidate.city or "").strip()
    state = (candidate.state or "").strip()
    country = (candidate.country or "").strip()
    if company:
        if not city:
            city = _city_from_headquarters(company.headquarters)
        if not state:
            state = _state_from_headquarters(company.headquarters)
        if not country:
            country = (company.country or "").strip()

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
        "associated note": _build_associated_note(candidate, company),
        "country/region": country,
        "city": city,
        "state/region": state,
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
) -> CompanyRow | None:
    return companies_by_name.get((candidate.company_name or "").strip().casefold())
