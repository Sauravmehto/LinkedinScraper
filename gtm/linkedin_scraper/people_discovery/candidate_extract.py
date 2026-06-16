"""Profile candidate extraction, normalization, and deduplication."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .types import PersonCandidate, RawProfileHit

LINKEDIN_IN_STRICT_RE = re.compile(
    r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_%\-\.]+/?$",
    re.IGNORECASE,
)


def normalize_profile_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))


def is_valid_profile_url(url: str) -> bool:
    normalized = normalize_profile_url(url)
    return bool(normalized and LINKEDIN_IN_STRICT_RE.match(normalized))


def dedupe_profile_hits(hits: list[RawProfileHit]) -> list[RawProfileHit]:
    deduped: list[RawProfileHit] = []
    seen: set[str] = set()
    for hit in hits:
        normalized = normalize_profile_url(hit.url)
        if not is_valid_profile_url(normalized):
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            RawProfileHit(
                url=normalized,
                source=hit.source,
                title=hit.title,
                snippet=hit.snippet,
                confidence_hint=hit.confidence_hint,
                person_name=hit.person_name,
                email=hit.email,
            )
        )
    return deduped


def normalize_person_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", (name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def dedupe_candidates_advanced(candidates: list[PersonCandidate]) -> list[PersonCandidate]:
    """Dedupe by LinkedIn URL, then by normalized name within company."""
    by_url: dict[str, PersonCandidate] = {}
    for c in candidates:
        key = c.linkedin_in_url.lower()
        prev = by_url.get(key)
        if prev is None or c.score > prev.score:
            by_url[key] = c

    by_name: dict[str, PersonCandidate] = {}
    for c in by_url.values():
        name_key = f"{c.company_name.lower()}|{normalize_person_name(c.person_name)}"
        if not normalize_person_name(c.person_name):
            by_name.setdefault(c.linkedin_in_url.lower(), c)
            continue
        prev = by_name.get(name_key)
        if prev is None or c.score > prev.score:
            by_name[name_key] = c
    return list(by_name.values())
