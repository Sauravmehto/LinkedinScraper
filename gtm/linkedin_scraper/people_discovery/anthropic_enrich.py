"""Optional Anthropic enrichment for people discovery candidates."""

from __future__ import annotations

import json
import re

import httpx

from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

from .candidate_extract import normalize_profile_url
from .types import RawProfileHit, RoleTarget

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def _parse_json_array(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    # Strip markdown code fences if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("candidates"), list):
            return [x for x in data["candidates"] if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    return []


def enrich_profile_hits(
    *,
    company_name: str,
    role_targets: list[RoleTarget],
    hits: list[RawProfileHit],
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 30.0,
    enrich_only: bool = False,
    batch_size: int = 30,
) -> list[RawProfileHit]:
    """
    Use Anthropic to assign names/titles/roles and optionally filter irrelevant profiles.
    When enrich_only=True, never drop hits (max coverage mode).
    """
    if not api_key or not hits:
        return hits

    enriched_all: list[RawProfileHit] = []
    role_names = [r.primary_role for r in role_targets[:16]]
    chunk_size = max(1, batch_size)

    for start in range(0, len(hits), chunk_size):
        capped = hits[start : start + chunk_size]
        payload_items = [
            {
                "linkedin_url": h.url,
                "title": h.title,
                "snippet": h.snippet,
                "source": h.source,
            }
            for h in capped
        ]

        system = (
            "You help identify senior decision makers at finance/real-estate companies. "
            "Return ONLY valid JSON: an array of objects with keys: "
            "linkedin_url, person_name, person_title, role_target, keep (boolean), reason. "
            "Set keep=false for wrong company, junior/unrelated roles, celebrity/obviously fake "
            "profiles (e.g. famous musicians), or weak title-company mismatches. "
            "role_target must be one of the requested roles or closest match."
        )
        if enrich_only:
            system += " In enrich-only mode set keep=true for all plausible profiles; only clean names/titles."

        user_content = json.dumps(
            {
                "company_name": company_name,
                "target_roles": role_names,
                "candidates": payload_items,
            },
            ensure_ascii=False,
        )

        body = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {
            **DEFAULT_HEADERS,
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            with httpx.Client(timeout=timeout, headers=headers) as client:
                resp = client.post(ANTHROPIC_API_URL, json=body)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, TimeoutError, OSError, ValueError, KeyError):
            enriched_all.extend(capped)
            continue

        content_blocks = data.get("content") or []
        text_parts = [
            b.get("text", "")
            for b in content_blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        parsed = _parse_json_array("\n".join(text_parts))
        if not parsed:
            enriched_all.extend(capped)
            continue

        by_url: dict[str, dict] = {}
        for row in parsed:
            url = normalize_profile_url(str(row.get("linkedin_url") or ""))
            if url:
                by_url[url.lower()] = row

        for hit in capped:
            row = by_url.get(hit.url.lower())
            if row is not None and row.get("keep") is False and not enrich_only:
                continue
            title = hit.title
            snippet = hit.snippet
            person_name = hit.person_name
            if row:
                title = str(row.get("person_title") or title).strip()
                person_name = str(row.get("person_name") or person_name).strip()
                role = str(row.get("role_target") or "").strip()
                if person_name:
                    snippet = f"{person_name} | {snippet}".strip(" |")
                if role and role not in title:
                    snippet = f"{snippet} | {role}".strip(" |")
            enriched_all.append(
                RawProfileHit(
                    url=hit.url,
                    source=hit.source,
                    title=title,
                    snippet=snippet,
                    confidence_hint=max(hit.confidence_hint, 0.75),
                    person_name=person_name,
                    email=hit.email,
                )
            )

    seen = {h.url.lower() for h in enriched_all}
    for hit in hits:
        if hit.url.lower() not in seen:
            enriched_all.append(hit)

    return enriched_all if enriched_all else hits
