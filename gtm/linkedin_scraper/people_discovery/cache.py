"""Disk cache for per-company people discovery results."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from gtm.linkedin_scraper.io_utils import OUTPUT_DIR

from .types import RawProfileHit

CACHE_DIR = OUTPUT_DIR / "cache" / "people"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s[:80] or "unknown"


def _domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def cache_path(company_name: str, website: str) -> Path:
    dom = _domain(website)
    key = f"{_slug(company_name)}__{_slug(dom)}" if dom else _slug(company_name)
    return CACHE_DIR / f"{key}.json"


def _hit_to_dict(hit: RawProfileHit) -> dict:
    return {
        "url": hit.url,
        "source": hit.source,
        "title": hit.title,
        "snippet": hit.snippet,
        "confidence_hint": hit.confidence_hint,
        "person_name": hit.person_name,
        "email": hit.email,
        "direct_dial": hit.direct_dial,
        "hq_phone": hit.hq_phone,
        "phone_source": hit.phone_source,
    }


def _hit_from_dict(data: dict) -> RawProfileHit:
    return RawProfileHit(
        url=str(data.get("url") or ""),
        source=str(data.get("source") or ""),
        title=str(data.get("title") or ""),
        snippet=str(data.get("snippet") or ""),
        confidence_hint=float(data.get("confidence_hint") or 0.0),
        person_name=str(data.get("person_name") or ""),
        email=str(data.get("email") or ""),
        direct_dial=str(data.get("direct_dial") or ""),
        hq_phone=str(data.get("hq_phone") or ""),
        phone_source=str(data.get("phone_source") or ""),
    )


def load_cached_hits(
    company_name: str,
    website: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> list[RawProfileHit] | None:
    path = cache_path(company_name, website)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(payload.get("saved_at") or 0)
        if time.time() - saved_at > ttl_seconds:
            return None
        rows = payload.get("hits") or []
        if not isinstance(rows, list):
            return None
        return [_hit_from_dict(r) for r in rows if isinstance(r, dict)]
    except (OSError, ValueError, TypeError):
        return None


def save_cached_hits(
    company_name: str,
    website: str,
    hits: list[RawProfileHit],
    *,
    meta: dict | None = None,
) -> None:
    path = cache_path(company_name, website)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "company_name": company_name,
        "website": website,
        "saved_at": time.time(),
        "hits": [_hit_to_dict(h) for h in hits],
        "meta": meta or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
