"""LinkedIn URL normalization and strict validation rules for fallbacks."""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from .types import LinkedInCandidate

LINKEDIN_COMPANY_RE = re.compile(
    r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[a-zA-Z0-9_%\-\.]+/?$",
    re.IGNORECASE,
)


def normalize_linkedin_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    if host.startswith("www."):
        host = host[4:]
    clean = urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))
    return clean


def is_valid_company_url(url: str) -> bool:
    normalized = normalize_linkedin_url(url)
    return bool(normalized and LINKEDIN_COMPANY_RE.match(normalized))


def dedupe_candidates(candidates: Iterable[LinkedInCandidate]) -> list[LinkedInCandidate]:
    out: list[LinkedInCandidate] = []
    seen: set[str] = set()
    for cand in candidates:
        normalized = normalize_linkedin_url(cand.url)
        if not is_valid_company_url(normalized):
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            LinkedInCandidate(
                url=normalized,
                source=cand.source,
                confidence=cand.confidence,
                reason=cand.reason,
            )
        )
    return out


def pick_best_candidate(candidates: Iterable[LinkedInCandidate]) -> LinkedInCandidate | None:
    filtered = dedupe_candidates(candidates)
    if not filtered:
        return None
    return sorted(filtered, key=lambda c: c.confidence, reverse=True)[0]
