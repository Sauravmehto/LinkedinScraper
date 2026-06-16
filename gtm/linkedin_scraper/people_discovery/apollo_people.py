"""Structured Apollo people search for decision-maker discovery."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from gtm.linkedin_scraper.fallbacks.common import post_json

from .candidate_extract import normalize_profile_url
from .types import RawProfileHit, RoleTarget

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"

_PREFERRED_DIRECT_TYPES = frozenset({"direct_dial", "mobile", "other"})
_PREFERRED_HQ_TYPES = frozenset({"work_hq", "work", "office", "hq"})


@dataclass(frozen=True)
class ApolloContact:
    work_email: str = ""
    email_status: str = ""
    email_confidence: str = ""
    direct_dial: str = ""
    hq_phone: str = ""
    phone_source: str = ""
    person_name: str = ""
    person_title: str = ""
    city: str = ""
    state: str = ""
    country: str = ""


def _domain_from_website(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _apollo_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _phone_number_from_entry(entry: dict) -> str:
    return (
        str(entry.get("sanitized_number") or entry.get("raw_number") or "").strip()
    )


def parse_apollo_phones(person: dict) -> tuple[str, str]:
    """Return (direct_dial, hq_phone) from Apollo person payload."""
    direct = ""
    hq = ""
    phones = person.get("phone_numbers") or []
    if isinstance(phones, list):
        for entry in phones:
            if not isinstance(entry, dict):
                continue
            num = _phone_number_from_entry(entry)
            if not num:
                continue
            ptype = str(entry.get("type") or "").lower()
            if ptype in _PREFERRED_DIRECT_TYPES and not direct:
                direct = num
            elif ptype in _PREFERRED_HQ_TYPES and not hq:
                hq = num
        if not direct:
            for entry in phones:
                if isinstance(entry, dict):
                    num = _phone_number_from_entry(entry)
                    if num:
                        direct = num
                        break
    org = person.get("organization")
    if isinstance(org, dict):
        org_phone = str(org.get("phone") or "").strip()
        if org_phone and not hq:
            hq = org_phone
    return direct, hq


def parse_apollo_contact(person: dict) -> ApolloContact:
    """Extract email and phones from an Apollo people/match person object."""
    email = str(person.get("email") or "").strip()
    direct, hq = parse_apollo_phones(person)
    phone_source = "apollo" if direct or hq else ""
    email_status = "from_apollo" if email else ""
    email_confidence = "from_apollo" if email else ""
    title = str(person.get("title") or person.get("headline") or "").strip()
    name = str(person.get("name") or "").strip()
    city = str(person.get("city") or "").strip()
    state = str(person.get("state") or "").strip()
    country = str(person.get("country") or "").strip()
    org = person.get("organization")
    if isinstance(org, dict):
        if not city:
            city = str(org.get("city") or "").strip()
        if not state:
            state = str(org.get("state") or "").strip()
        if not country:
            country = str(org.get("country") or "").strip()
    return ApolloContact(
        work_email=email,
        email_status=email_status,
        email_confidence=email_confidence,
        direct_dial=direct,
        hq_phone=hq,
        phone_source=phone_source,
        person_name=name,
        person_title=title,
        city=city,
        state=state,
        country=country,
    )


def _match_person_request(
    *,
    api_key: str,
    timeout: float,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict | None:
    try:
        import httpx

        with httpx.Client(timeout=timeout, headers=_apollo_headers(api_key)) as client:
            resp = client.post(
                APOLLO_MATCH_URL,
                params=params,
                json=json_body,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    person = data.get("person") if isinstance(data, dict) else None
    return person if isinstance(person, dict) else None


def match_person_by_id(
    person_id: str,
    *,
    api_key: str,
    timeout: float,
) -> dict | None:
    if not person_id:
        return None
    return _match_person_request(
        api_key=api_key,
        timeout=timeout,
        params={"id": person_id},
    )


def match_person_by_linkedin(
    linkedin_url: str,
    *,
    api_key: str,
    timeout: float,
    reveal_phone_number: bool = True,
    reveal_personal_emails: bool = False,
    domain: str | None = None,
) -> dict | None:
    url = normalize_profile_url(linkedin_url)
    if not url or "/in/" not in url.lower():
        return None
    body: dict = {
        "linkedin_url": url,
        "reveal_personal_emails": reveal_personal_emails,
    }
    if domain:
        body["domain"] = domain.strip().lower()
    if reveal_phone_number:
        body["reveal_phone_number"] = True
    return _match_person_request(
        api_key=api_key,
        timeout=timeout,
        json_body=body,
    )


def _person_to_hit(person: dict, *, role_hint: str) -> RawProfileHit | None:
    url = normalize_profile_url(str(person.get("linkedin_url") or ""))
    if not url or "/in/" not in url.lower():
        return None
    title = (person.get("title") or person.get("headline") or role_hint or "").strip()
    name = (person.get("name") or "").strip()
    org = ""
    org_obj = person.get("organization")
    if isinstance(org_obj, dict):
        org = str(org_obj.get("name") or "").strip()
    contact = parse_apollo_contact(person)
    snippet = " | ".join(x for x in (name, org, title) if x)
    return RawProfileHit(
        url=url,
        source="apollo",
        title=title,
        snippet=snippet,
        confidence_hint=0.92,
        person_name=name,
        email=contact.work_email,
        direct_dial=contact.direct_dial,
        hq_phone=contact.hq_phone,
        phone_source=contact.phone_source,
    )


def search_apollo_company(
    *,
    company_name: str,
    website: str = "",
    role_targets: list[RoleTarget],
    api_key: str,
    timeout: float = 15.0,
    max_roles: int = 5,
    max_enrich: int = 15,
    match_delay: float = 0.0,
) -> list[RawProfileHit]:
    """
    Search Apollo (api_search) then enrich each person (people/match) for linkedin_url.
    """
    if not api_key or not company_name:
        return []

    titles: list[str] = []
    for role in role_targets[:max_roles]:
        titles.append(role.primary_role)
        titles.extend(role.expanded_roles[:2])
    titles = list(dict.fromkeys(t for t in titles if t))[:12]

    domain = _domain_from_website(website)
    payload: dict = {
        "q_organization_name": company_name,
        "person_titles": titles,
        "page": 1,
        "per_page": min(max_enrich, 25),
    }
    if domain:
        payload["q_organization_domains_list"] = [domain]

    data = post_json(
        APOLLO_SEARCH_URL,
        payload,
        timeout=timeout,
        headers=_apollo_headers(api_key),
    )
    if not data:
        return []

    people = data.get("people") or []
    if not isinstance(people, list):
        return []

    hits: list[RawProfileHit] = []
    seen_urls: set[str] = set()

    for stub in people[:max_enrich]:
        if not isinstance(stub, dict):
            continue
        person_id = str(stub.get("id") or "").strip()
        if not person_id:
            continue
        enriched = match_person_by_id(person_id, api_key=api_key, timeout=timeout)
        if match_delay > 0:
            time.sleep(match_delay)
        if not enriched:
            continue
        role_hint = str(stub.get("title") or titles[0] if titles else "")
        hit = _person_to_hit(enriched, role_hint=role_hint)
        if not hit:
            continue
        key = hit.url.lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        hits.append(hit)

    return hits
