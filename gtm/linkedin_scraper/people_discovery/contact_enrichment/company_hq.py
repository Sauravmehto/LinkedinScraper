"""Backfill hq_phone from company domain (Apollo org enrich) and peer rows."""

from __future__ import annotations

import time
from typing import Callable

import httpx

from gtm.linkedin_scraper.hubspot_sync.client import domain_from_website
from gtm.linkedin_scraper.people_discovery.apollo_people import _apollo_headers
from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

APOLLO_ORG_ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"

_ORG_PHONE_CACHE: dict[str, str] = {}


def _company_key(name: str) -> str:
    return (name or "").strip().casefold()


def fetch_organization_phone(
    domain: str,
    *,
    api_key: str,
    timeout: float = 15.0,
) -> str:
    """Apollo organizations/enrich — returns org main phone if available."""
    domain = (domain or "").strip().lower()
    if not domain or not api_key:
        return ""
    if domain in _ORG_PHONE_CACHE:
        return _ORG_PHONE_CACHE[domain]

    phone = ""
    try:
        with httpx.Client(timeout=timeout, headers=_apollo_headers(api_key)) as client:
            resp = client.get(APOLLO_ORG_ENRICH_URL, params={"domain": domain})
            resp.raise_for_status()
            data = resp.json()
        org = data.get("organization") if isinstance(data, dict) else None
        if isinstance(org, dict):
            phone = str(org.get("phone") or org.get("primary_phone") or "").strip()
            if not phone:
                san = org.get("sanitized_phone")
                if san:
                    phone = str(san).strip()
    except Exception:
        phone = ""

    _ORG_PHONE_CACHE[domain] = phone
    return phone


def _with_hq(
    candidate: PersonCandidate,
    hq: str,
    *,
    phone_source: str,
) -> PersonCandidate:
    return PersonCandidate(
        company_name=candidate.company_name,
        company_type=candidate.company_type,
        company_linkedin=candidate.company_linkedin,
        company_website=candidate.company_website,
        role_target=candidate.role_target,
        person_name=candidate.person_name,
        person_title=candidate.person_title,
        linkedin_in_url=candidate.linkedin_in_url,
        source=candidate.source,
        snippet=candidate.snippet,
        score=candidate.score,
        confidence=candidate.confidence,
        notes=candidate.notes,
        work_email=candidate.work_email,
        personal_email=candidate.personal_email,
        email_status=candidate.email_status,
        email_confidence=candidate.email_confidence,
        direct_dial=candidate.direct_dial,
        hq_phone=hq,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=phone_source or candidate.phone_source,
        phone_status=candidate.phone_status,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
    )


def backfill_hq_phones(
    candidates: list[PersonCandidate],
    *,
    websites_by_company: dict[str, str] | None = None,
    company_hq_by_name: dict[str, str] | None = None,
    api_key: str | None = None,
    timeout: float = 15.0,
    org_delay: float = 0.35,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], int]:
    """
    Fill empty hq_phone from:
    1) company_hq_by_name (Excel / explicit map)
    2) Apollo organization enrich by domain (from websites_by_company)
    3) hq_phone already present on another person at the same company
    """
    _log = log or (lambda _m: None)
    websites = websites_by_company or {}
    explicit_norm = {
        _company_key(k): (v or "").strip()
        for k, v in (company_hq_by_name or {}).items()
        if (v or "").strip()
    }

    domain_by_company: dict[str, str] = {}
    for name, site in websites.items():
        key = _company_key(name)
        if key and site:
            dom = domain_from_website(site)
            if dom:
                domain_by_company[key] = dom

    org_phone_by_company: dict[str, str] = {}
    if api_key:
        seen_domains: set[str] = set()
        for key, dom in domain_by_company.items():
            if dom in seen_domains:
                continue
            seen_domains.add(dom)
            phone = fetch_organization_phone(dom, api_key=api_key, timeout=timeout)
            if phone:
                org_phone_by_company[key] = phone
            if org_delay > 0:
                time.sleep(org_delay)

    peer_hq: dict[str, str] = {}
    for c in candidates:
        hq = (c.hq_phone or "").strip()
        if hq:
            peer_hq[_company_key(c.company_name)] = hq

    filled = 0
    out: list[PersonCandidate] = []
    for c in candidates:
        if (c.hq_phone or "").strip():
            out.append(c)
            continue

        key = _company_key(c.company_name)
        hq = explicit_norm.get(key, "")
        source = "company_excel" if hq else ""

        if not hq:
            hq = org_phone_by_company.get(key, "")
            if hq:
                source = "company_apollo_org"

        if not hq:
            hq = peer_hq.get(key, "")
            if hq:
                source = "company_peer"

        if hq:
            filled += 1
            peer_hq.setdefault(key, hq)
            out.append(_with_hq(c, hq, phone_source=source))
        else:
            out.append(c)

    if filled:
        _log(f"HQ phone backfill: filled {filled} row(s) from company org/peer/excel")
    return out, filled
