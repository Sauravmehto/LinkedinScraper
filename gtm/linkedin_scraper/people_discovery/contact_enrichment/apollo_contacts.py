"""Apollo people/match enrichment for contact details."""

from __future__ import annotations

import time
from typing import Callable

from gtm.linkedin_scraper.hubspot_sync.client import domain_from_website

from ..apollo_people import ApolloContact, match_person_by_linkedin, parse_apollo_contact
from ..candidate_extract import normalize_profile_url
from ..types import PersonCandidate

ApolloMatchCache = dict[str, ApolloContact]


def _needs_apollo_enrichment(candidate: PersonCandidate, *, only_missing: bool) -> bool:
    if not only_missing:
        return True
    missing_email = not (
        (candidate.work_email or "").strip() or (candidate.personal_email or "").strip()
    )
    missing_phone = not (
        (candidate.direct_dial or "").strip() or (candidate.hq_phone or "").strip()
    )
    missing_city = not (candidate.city or "").strip()
    return missing_email or missing_phone or missing_city


def _merge_contact(
    candidate: PersonCandidate,
    contact: ApolloContact,
) -> PersonCandidate:
    work_email = (candidate.work_email or "").strip() or contact.work_email
    personal_email = (candidate.personal_email or "").strip() or contact.personal_email
    email_status = candidate.email_status
    email_confidence = candidate.email_confidence
    if contact.work_email and not (candidate.work_email or "").strip():
        email_status = contact.email_status or "from_apollo"
        email_confidence = contact.email_confidence or "from_apollo"
    elif contact.personal_email and not (candidate.personal_email or "").strip():
        email_status = contact.email_status or "from_apollo_personal"
        email_confidence = contact.email_confidence or "from_apollo_personal"
    direct = (candidate.direct_dial or "").strip() or contact.direct_dial
    hq = (candidate.hq_phone or "").strip() or contact.hq_phone
    phone_source = candidate.phone_source
    if (direct or hq) and not phone_source:
        phone_source = contact.phone_source or "apollo"
    person_name = (candidate.person_name or "").strip() or contact.person_name
    person_title = (candidate.person_title or "").strip() or contact.person_title
    city = (candidate.city or "").strip() or contact.city
    state = (candidate.state or "").strip() or contact.state
    country = (candidate.country or "").strip() or contact.country
    return PersonCandidate(
        company_name=candidate.company_name,
        company_type=candidate.company_type,
        company_linkedin=candidate.company_linkedin,
        company_website=candidate.company_website,
        role_target=candidate.role_target,
        person_name=person_name,
        person_title=person_title,
        linkedin_in_url=candidate.linkedin_in_url,
        source=candidate.source,
        snippet=candidate.snippet,
        score=candidate.score,
        confidence=candidate.confidence,
        notes=candidate.notes,
        work_email=work_email,
        personal_email=personal_email,
        email_status=email_status,
        email_confidence=email_confidence,
        direct_dial=direct,
        hq_phone=hq,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=phone_source,
        phone_status=candidate.phone_status,
        city=city,
        state=state,
        country=country,
    )


def enrich_person_via_apollo(
    candidate: PersonCandidate,
    *,
    api_key: str,
    timeout: float,
    cache: ApolloMatchCache,
    only_missing: bool = True,
    reveal_phone_number: bool = True,
    reveal_personal_emails: bool = True,
    match_delay: float = 0.5,
) -> tuple[PersonCandidate, bool]:
    """
    Enrich one person via Apollo people/match. Returns (candidate, apollo_called).
    """
    if not api_key or not candidate.linkedin_in_url:
        return candidate, False
    if not _needs_apollo_enrichment(candidate, only_missing=only_missing):
        return candidate, False

    key = normalize_profile_url(candidate.linkedin_in_url).lower()
    if not key:
        return candidate, False

    if key in cache:
        return _merge_contact(candidate, cache[key]), False

    dom = domain_from_website(candidate.company_website)
    person = match_person_by_linkedin(
        candidate.linkedin_in_url,
        api_key=api_key,
        timeout=timeout,
        reveal_phone_number=reveal_phone_number,
        reveal_personal_emails=reveal_personal_emails,
        domain=dom or None,
    )
    if match_delay > 0:
        time.sleep(match_delay)

    if not person:
        cache[key] = ApolloContact()
        return candidate, True

    contact = parse_apollo_contact(person)
    cache[key] = contact
    return _merge_contact(candidate, contact), True


def enrich_list_via_apollo(
    candidates: list[PersonCandidate],
    *,
    api_key: str,
    timeout: float,
    only_missing: bool = True,
    reveal_phone_number: bool = True,
    reveal_personal_emails: bool = True,
    match_delay: float = 0.5,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], int, ApolloMatchCache]:
    cache: ApolloMatchCache = {}
    apollo_calls = 0
    out: list[PersonCandidate] = []

    for c in candidates:
        updated, called = enrich_person_via_apollo(
            c,
            api_key=api_key,
            timeout=timeout,
            cache=cache,
            only_missing=only_missing,
            reveal_phone_number=reveal_phone_number,
            reveal_personal_emails=reveal_personal_emails,
            match_delay=match_delay,
        )
        if called:
            apollo_calls += 1
        out.append(updated)

    if log and apollo_calls:
        log(f"Apollo contact enrichment: {apollo_calls} people/match call(s)")
    return out, apollo_calls, cache
