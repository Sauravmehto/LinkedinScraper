"""Quality checks for decision-maker profile hits."""

from __future__ import annotations

import re

from .candidate_extract import is_valid_profile_url, normalize_profile_url
from .types import RawProfileHit

SENIORITY_HINTS = (
    "chief",
    "cfo",
    "coo",
    "cio",
    "cto",
    "director",
    "managing director",
    "partner",
    "principal",
    "head of",
    "vp",
    "president",
)


def _token_count(name: str) -> int:
    return len([p for p in (name or "").split() if p])


def _looks_like_real_name(name: str) -> bool:
    name = (name or "").strip()
    if _token_count(name) < 2:
        return False
    if re.search(r"\d{3,}", name):
        return False
    return True


def _company_in_blob(blob: str, company_name: str) -> bool:
    company_low = (company_name or "").lower()
    if not company_low:
        return True
    return company_low in blob.lower()


def _title_or_role_signal(hit: RawProfileHit, company_name: str) -> bool:
    blob = f"{hit.title} {hit.snippet}".lower()
    if _company_in_blob(blob, company_name):
        return True
    return any(h in blob for h in SENIORITY_HINTS)


def is_quality_profile(
    hit: RawProfileHit,
    *,
    company_name: str = "",
) -> bool:
    """
    A profile counts toward fallback thresholds when it has a valid LinkedIn /in/ URL
    and enough identity signals (name, title/company, or high-trust source).
    """
    if not is_valid_profile_url(normalize_profile_url(hit.url)):
        return False

    name = (hit.person_name or "").strip()
    if not name and hit.snippet:
        name = hit.snippet.split(" | ")[0].strip()

    if hit.source in ("apollo", "team_page"):
        return _looks_like_real_name(name) or bool((hit.title or "").strip())

    if _looks_like_real_name(name) and _title_or_role_signal(hit, company_name):
        return True

    return False


def count_quality_profiles(
    hits: list[RawProfileHit],
    *,
    company_name: str = "",
) -> int:
    return sum(1 for h in hits if is_quality_profile(h, company_name=company_name))
