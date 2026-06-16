"""Apollo people/match phone reveal (async via webhook + poll)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..apollo_people import (
    APOLLO_MATCH_URL,
    _apollo_headers,
    _domain_from_website,
    parse_apollo_contact,
    parse_apollo_phones,
)
from ..candidate_extract import normalize_profile_url
from ..types import PersonCandidate

APOLLO_POLL_URL = "https://api.apollo.io/api/v1/webhook_results/poll"


def split_person_name(full: str) -> tuple[str, str]:
    text = (full or "").strip()
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


@dataclass(frozen=True)
class PhoneRevealResult:
    request_id: str
    direct_dial: str
    hq_phone: str
    phone_source: str
    phone_status: str
    person: dict | None = None


def submit_phone_reveal(
    candidate: PersonCandidate,
    *,
    api_key: str,
    webhook_url: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    POST people/match with reveal_phone_number=true.
    Returns full Apollo JSON (includes request_id; phones usually arrive async).
    """
    if not api_key or not webhook_url:
        return {}
    first, last = split_person_name(candidate.person_name)
    domain = _domain_from_website(candidate.company_website)
    linkedin = normalize_profile_url(candidate.linkedin_in_url)
    body: dict[str, Any] = {
        "reveal_phone_number": True,
        "reveal_personal_emails": False,
        "run_waterfall_email": False,
        "run_waterfall_phone": False,
        "webhook_url": webhook_url.strip(),
    }
    if linkedin:
        body["linkedin_url"] = linkedin
    if first:
        body["first_name"] = first
    if last:
        body["last_name"] = last
    if domain:
        body["domain"] = domain
    email = (candidate.work_email or "").strip()
    if email and "@" in email:
        body["email"] = email

    with httpx.Client(timeout=timeout, headers=_apollo_headers(api_key)) as client:
        resp = client.post(APOLLO_MATCH_URL, json=body)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, dict) else {}


def poll_webhook_result(
    request_id: str,
    *,
    api_key: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not request_id or not api_key:
        return {}
    with httpx.Client(timeout=timeout, headers=_apollo_headers(api_key)) as client:
        resp = client.get(
            APOLLO_POLL_URL,
            params={"request_id": request_id},
        )
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, dict) else {}


def _phones_from_payload(payload: dict) -> tuple[str, str]:
    person = payload.get("person")
    if not isinstance(person, dict):
        person = payload
    if isinstance(person, dict):
        contact = parse_apollo_contact(person)
        if contact.direct_dial or contact.hq_phone:
            return contact.direct_dial, contact.hq_phone
        direct, hq = parse_apollo_phones(person)
        return direct, hq
    return "", ""


def wait_for_phones(
    request_id: str,
    *,
    api_key: str,
    poll_timeout: float = 120.0,
    poll_interval: float = 5.0,
    request_timeout: float = 30.0,
    log: Callable[[str], None] | None = None,
) -> PhoneRevealResult:
    _log = log or (lambda _m: None)
    deadline = time.time() + poll_timeout
    last_payload: dict[str, Any] = {}

    while time.time() < deadline:
        try:
            last_payload = poll_webhook_result(
                request_id,
                api_key=api_key,
                timeout=request_timeout,
            )
        except httpx.HTTPError as exc:
            _log(f"Poll error for {request_id}: {exc}")
            time.sleep(poll_interval)
            continue

        direct, hq = _phones_from_payload(last_payload)
        if direct or hq:
            person = last_payload.get("person")
            return PhoneRevealResult(
                request_id=request_id,
                direct_dial=direct,
                hq_phone=hq,
                phone_source="apollo_poll",
                phone_status="received",
                person=person if isinstance(person, dict) else None,
            )

        status = str(last_payload.get("status") or "").lower()
        if status in ("failed", "error", "not_found"):
            break

        time.sleep(poll_interval)

    return PhoneRevealResult(
        request_id=request_id,
        direct_dial="",
        hq_phone="",
        phone_source="",
        phone_status="timeout",
        person=last_payload.get("person") if isinstance(last_payload.get("person"), dict) else None,
    )


def reveal_and_poll_phones(
    candidate: PersonCandidate,
    *,
    api_key: str,
    webhook_url: str,
    poll_timeout: float = 120.0,
    poll_interval: float = 5.0,
    request_timeout: float = 30.0,
    submit_delay: float = 0.5,
    log: Callable[[str], None] | None = None,
) -> tuple[PersonCandidate, PhoneRevealResult | None]:
    """Submit match request, poll for phones, return updated candidate."""
    _log = log or (lambda _m: None)
    if (candidate.direct_dial or "").strip():
        return candidate, None

    try:
        data = submit_phone_reveal(
            candidate,
            api_key=api_key,
            webhook_url=webhook_url,
            timeout=request_timeout,
        )
    except httpx.HTTPError as exc:
        _log(f"Submit failed for {candidate.person_name}: {exc}")
        updated = _with_phone_fields(candidate, phone_status="submit_error")
        return updated, None

    if submit_delay > 0:
        time.sleep(submit_delay)

    request_id = str(data.get("request_id") or "").strip()
    person = data.get("person") if isinstance(data.get("person"), dict) else None

    direct, hq = _phones_from_payload(data)
    if direct or hq:
        return (
            _with_phone_fields(
                candidate,
                direct_dial=direct,
                hq_phone=hq or (candidate.hq_phone or ""),
                phone_source="apollo_sync",
                phone_status="received",
            ),
            PhoneRevealResult(
                request_id=request_id,
                direct_dial=direct,
                hq_phone=hq,
                phone_source="apollo_sync",
                phone_status="received",
                person=person,
            ),
        )

    if not request_id:
        _log(f"No request_id for {candidate.person_name}; sync response had no phones")
        return _with_phone_fields(candidate, phone_status="no_request_id"), None

    _log(f"Polling phones request_id={request_id} for {candidate.person_name}")
    result = wait_for_phones(
        request_id,
        api_key=api_key,
        poll_timeout=poll_timeout,
        poll_interval=poll_interval,
        request_timeout=request_timeout,
        log=_log,
    )

    if result.direct_dial or result.hq_phone:
        return (
            _with_phone_fields(
                candidate,
                direct_dial=result.direct_dial,
                hq_phone=result.hq_phone or (candidate.hq_phone or ""),
                phone_source=result.phone_source,
                phone_status=result.phone_status,
            ),
            result,
        )

    return _with_phone_fields(candidate, phone_status=result.phone_status), result


def _with_phone_fields(
    candidate: PersonCandidate,
    *,
    direct_dial: str | None = None,
    hq_phone: str | None = None,
    phone_source: str | None = None,
    phone_status: str | None = None,
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
        email_status=candidate.email_status,
        email_confidence=candidate.email_confidence,
        direct_dial=direct_dial if direct_dial is not None else candidate.direct_dial,
        hq_phone=hq_phone if hq_phone is not None else candidate.hq_phone,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=phone_source if phone_source is not None else candidate.phone_source,
        phone_status=phone_status if phone_status is not None else candidate.phone_status,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
    )
