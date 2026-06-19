"""Map GTM Excel rows to HubSpot CRM properties."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

from .client import domain_from_website


def split_person_name(full: str) -> tuple[str, str]:
    text = (full or "").strip()
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


@dataclass(frozen=True)
class CompanyRow:
    name: str
    website: str
    company_linkedin: str
    country: str = ""
    headquarters: str = ""
    aum: str = ""
    asset_type: str = ""
    hq_phone: str = ""


def company_row_from_excel(
    *,
    name: str,
    website: str,
    profile_url: str,
    country: str = "",
    headquarters: str = "",
    aum: str = "",
    asset_type: str = "",
    hq_phone: str = "",
) -> CompanyRow | None:
    name = (name or "").strip()
    if not name:
        return None
    return CompanyRow(
        name=name,
        website=(website or "").strip(),
        company_linkedin=(profile_url or "").strip(),
        country=(country or "").strip(),
        headquarters=(headquarters or "").strip(),
        aum=(aum or "").strip(),
        asset_type=(asset_type or "").strip(),
        hq_phone=(hq_phone or "").strip(),
    )


def company_properties(
    row: CompanyRow,
    *,
    extra_props: dict[str, str] | None = None,
) -> dict[str, str]:
    domain = domain_from_website(row.website)
    props: dict[str, str] = {"name": row.name}
    if domain:
        props["domain"] = domain
    if row.website:
        props["website"] = row.website if row.website.startswith("http") else f"https://{row.website}"
    desc_parts = []
    if row.company_linkedin:
        desc_parts.append(f"LinkedIn company: {row.company_linkedin}")
    if row.asset_type:
        desc_parts.append(f"Focus: {row.asset_type}")
    if row.aum:
        desc_parts.append(f"AUM: {row.aum}")
    if desc_parts:
        props["description"] = " | ".join(desc_parts)[:65536]
    if extra_props:
        for key, val in extra_props.items():
            if val:
                props[key] = val
    return props


def contact_properties(
    candidate: PersonCandidate,
    *,
    lifecycle_stage: str = "lead",
    lead_status: str = "",
    owner_id: str = "",
    person_linkedin_prop: str = "",
    extra_props: dict[str, str] | None = None,
) -> dict[str, str]:
    first, last = split_person_name(candidate.person_name)
    email = (
        (candidate.work_email or candidate.personal_email or "").strip().lower()
    )
    phone = (candidate.direct_dial or candidate.hq_phone or "").strip()
    props: dict[str, str] = {}
    if email:
        props["email"] = email
    if first:
        props["firstname"] = first
    if last:
        props["lastname"] = last
    title = (candidate.person_title or candidate.role_target or "").strip()
    if title:
        props["jobtitle"] = title[:255]
    company = (candidate.company_name or "").strip()
    if company:
        props["company"] = company[:255]
    website = (candidate.company_website or "").strip()
    if website:
        props["website"] = website if website.startswith("http") else f"https://{website}"
    if phone:
        props["phone"] = phone[:50]
        props["mobilephone"] = phone[:50]
    if lifecycle_stage:
        props["lifecyclestage"] = lifecycle_stage
    if lead_status:
        props["hs_lead_status"] = lead_status
    if owner_id:
        props["hubspot_owner_id"] = owner_id
    linkedin = (candidate.linkedin_in_url or "").strip()
    if linkedin and person_linkedin_prop:
        props[person_linkedin_prop] = linkedin
    if extra_props:
        for key, val in extra_props.items():
            if val:
                props[key] = val
    return props


def contact_import_note(candidate: PersonCandidate) -> str:
    lines = [
        "GTM import",
        f"Score: {candidate.score} ({candidate.confidence})",
        f"Role target: {candidate.role_target}",
        f"Source: {candidate.source}",
    ]
    if candidate.linkedin_in_url:
        lines.append(f"Person LinkedIn: {candidate.linkedin_in_url}")
    if candidate.company_linkedin:
        lines.append(f"Company LinkedIn: {candidate.company_linkedin}")
    if candidate.email_confidence:
        lines.append(f"Email confidence: {candidate.email_confidence}")
    if candidate.phone_source:
        lines.append(f"Phone source: {candidate.phone_source}")
    return "\n".join(lines)
