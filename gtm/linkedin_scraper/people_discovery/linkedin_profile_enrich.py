"""LinkedIn /in/ profile enrichment for clean job titles."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from gtm.linkedin_scraper.config import load_fallback_config
from gtm.linkedin_scraper.people_discovery.anthropic_enrich import DEFAULT_MODEL
from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS
from gtm.linkedin_scraper.scrapers.linkedin_extract import make_soup

from .candidate_extract import normalize_profile_url
from .types import PersonCandidate

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

TITLE_DATE_PRESENT = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[\w\s,.-]*?\bPresent\b",
    re.I,
)
HEADLINE_AT = re.compile(r"^(.+?)\s+at\s+", re.I)
JSON_LD_SCRIPT = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
LOGIN_WALL_MARKERS = (
    "authwall",
    "join linkedin",
    "sign in",
    "login-form",
    "session_redirect",
)


@dataclass
class LinkedInTitleStats:
    candidates_in: int = 0
    profiles_fetched: int = 0
    titles_updated: int = 0
    anthropic_verified: int = 0
    fetch_failures: int = 0
    by_url: dict[str, str] = field(default_factory=dict)


def is_messy_title(title: str, *, person_name: str = "") -> bool:
    """True when title looks like a search snippet rather than a role."""
    text = (title or "").strip()
    if not text:
        return True
    if len(text) > 80:
        return True
    if text.count(" - ") >= 1:
        return True
    if " at " in text.lower() and len(text) > 45:
        return True
    if person_name:
        first = person_name.split()[0].strip()
        if first and len(first) > 2 and first.lower() in text.lower():
            return True
    return False


def _looks_like_job_title(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 120:
        return False
    lower = cleaned.lower()
    blocked = {
        "connections",
        "message",
        "follow",
        "more",
        "contact info",
        "· 3rd",
        "3rd",
        "2nd",
        "1st",
    }
    if lower in blocked:
        return False
    if lower.startswith("·"):
        return False
    return True


def _strip_headline(title: str) -> str:
    text = (title or "").strip()
    match = HEADLINE_AT.match(text)
    if match:
        return match.group(1).strip()
    return text


def _json_ld_title(html: str) -> str:
    for match in JSON_LD_SCRIPT.finditer(html or ""):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("jobTitle") or "").strip()
            if title and _looks_like_job_title(title):
                return title
    return ""


def _find_experience_section(soup):
    section = soup.find(attrs={"data-testid": re.compile(r"profile_Experience", re.I)})
    if section is not None:
        return section
    for heading in soup.find_all(["h2", "h3"]):
        if (heading.get_text(strip=True) or "").lower() == "experience":
            parent = heading.find_parent("section") or heading.find_parent("div")
            if parent is not None:
                return parent
    return None


def _experience_title_from_soup(soup, *, company_name: str = "") -> str:
    section = _find_experience_section(soup)
    if section is None:
        return ""

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in section.find_all("p")
        if p.get_text(strip=True)
    ]
    company_key = (company_name or "").strip().casefold()

    for idx, text in enumerate(paragraphs):
        if not TITLE_DATE_PRESENT.search(text):
            continue
        if idx == 0:
            continue
        candidate = paragraphs[idx - 1].strip()
        if not _looks_like_job_title(candidate):
            continue
        if company_key:
            window = " ".join(paragraphs[max(0, idx - 3) : idx + 2]).casefold()
            if company_key not in window and len(paragraphs) > 3:
                continue
        return candidate
    return ""


def _headline_title_from_soup(soup, *, company_name: str = "") -> str:
    company_key = (company_name or "").strip().casefold()
    for paragraph in soup.find_all("p"):
        text = paragraph.get_text(" ", strip=True)
        if " at " not in text or TITLE_DATE_PRESENT.search(text):
            continue
        title = _strip_headline(text)
        if not _looks_like_job_title(title):
            continue
        if company_key and company_key not in text.casefold():
            continue
        return title
    return ""


def extract_titles_from_html(html: str, *, company_name: str = "") -> dict[str, str]:
    """Return headline, experience, and json-ld title candidates from profile HTML."""
    if not html or len(html.strip()) < 200:
        return {"headline_title": "", "experience_title": "", "json_ld_title": ""}

    lower = html.casefold()
    if any(marker in lower for marker in LOGIN_WALL_MARKERS):
        return {"headline_title": "", "experience_title": "", "json_ld_title": ""}

    soup = make_soup(html)
    return {
        "headline_title": _headline_title_from_soup(soup, company_name=company_name),
        "experience_title": _experience_title_from_soup(soup, company_name=company_name),
        "json_ld_title": _json_ld_title(html),
    }


def pick_best_raw_title(
    extracted: dict[str, str],
    *,
    current_title: str = "",
    person_name: str = "",
) -> str:
    """Prefer Experience section title, then cleaned headline, then JSON-LD."""
    for key in ("experience_title", "headline_title", "json_ld_title"):
        candidate = (extracted.get(key) or "").strip()
        if candidate and _looks_like_job_title(candidate):
            if not is_messy_title(candidate, person_name=person_name):
                return candidate

    for key in ("experience_title", "headline_title", "json_ld_title"):
        candidate = (extracted.get(key) or "").strip()
        if candidate and _looks_like_job_title(candidate):
            return candidate

    current = (current_title or "").strip()
    if current and not is_messy_title(current, person_name=person_name):
        return current
    if current:
        stripped = _strip_headline(current)
        if stripped and _looks_like_job_title(stripped):
            return stripped
    return ""


def fetch_linkedin_profile_html(url: str, *, timeout: float = 30.0) -> str | None:
    """Render a LinkedIn profile page in headless Chromium."""
    normalized = normalize_profile_url(url)
    if not normalized or "/in/" not in normalized.lower():
        return None
    try:
        from gtm.linkedin_scraper.scrapers import step3_playwright

        context, err = step3_playwright._ensure_context()
        if err is not None or context is None:
            return None

        page = context.new_page()
        try:
            page.goto(normalized, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            page.wait_for_timeout(1200)
            html = page.content()
            return html if html and len(html.strip()) >= 200 else None
        finally:
            page.close()
    except Exception:
        return None


def _parse_json_array(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return [row for row in data["rows"] if isinstance(row, dict)]
    except json.JSONDecodeError:
        pass
    return []


def verify_titles_with_anthropic(
    items: list[dict],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict[str, str]:
    """Return linkedin_url -> verified short job title."""
    if not api_key or not items:
        return {}

    system = (
        "You normalize LinkedIn job titles for a CRM export. "
        "Return ONLY valid JSON: {\"rows\": [{\"linkedin_url\": \"...\", "
        "\"job_title\": \"...\"}]}. "
        "Output ONLY the role (e.g. 'SVP, Chief Accounting Officer'). "
        "Do NOT include person name, credentials (CPA), company name, location, "
        "or connection degree. Prefer current Experience role over headline. "
        "If unsure, return the shortest accurate title."
    )
    user = json.dumps({"profiles": items}, ensure_ascii=False)

    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS) as client:
            resp = client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 2048,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return {}

    text_blocks = payload.get("content") or []
    text = ""
    for block in text_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text += str(block.get("text") or "")

    rows = _parse_json_array(text)
    out: dict[str, str] = {}
    for row in rows:
        url = normalize_profile_url(str(row.get("linkedin_url") or ""))
        title = str(row.get("job_title") or "").strip()
        if url and title and _looks_like_job_title(title):
            out[url.lower()] = title
    return out


def _with_title(candidate: PersonCandidate, title: str) -> PersonCandidate:
    cleaned = (title or "").strip()
    if not cleaned:
        return candidate
    return PersonCandidate(
        company_name=candidate.company_name,
        company_type=candidate.company_type,
        company_linkedin=candidate.company_linkedin,
        company_website=candidate.company_website,
        role_target=candidate.role_target,
        person_name=candidate.person_name,
        person_title=cleaned,
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
        hq_phone=candidate.hq_phone,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=candidate.phone_source,
        phone_status=candidate.phone_status,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
    )


def enrich_linkedin_job_titles(
    candidates: list[PersonCandidate],
    *,
    api_key: str | None = None,
    model: str | None = None,
    enable_anthropic: bool = True,
    profile_delay: float = 2.0,
    timeout: float = 30.0,
    only_messy: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], LinkedInTitleStats]:
    """Fetch LinkedIn profiles and replace messy titles with verified roles."""
    _log = log or (lambda _msg: None)
    stats = LinkedInTitleStats(candidates_in=len(candidates))

    cfg = load_fallback_config()
    anthropic_key = api_key or cfg.anthropic_api_key
    anthropic_model = model or cfg.anthropic_model or DEFAULT_MODEL

    pending: list[tuple[int, PersonCandidate, dict[str, str], str]] = []
    results: list[PersonCandidate | None] = [None] * len(candidates)

    for idx, candidate in enumerate(candidates):
        url = normalize_profile_url(candidate.linkedin_in_url)
        if not url:
            results[idx] = candidate
            continue

        current = (candidate.person_title or "").strip()
        if only_messy and not is_messy_title(current, person_name=candidate.person_name):
            results[idx] = candidate
            continue

        html = fetch_linkedin_profile_html(url, timeout=timeout)
        if not html:
            stats.fetch_failures += 1
            results[idx] = candidate
            if profile_delay > 0:
                time.sleep(profile_delay)
            continue

        stats.profiles_fetched += 1
        extracted = extract_titles_from_html(html, company_name=candidate.company_name)
        raw_title = pick_best_raw_title(
            extracted,
            current_title=current,
            person_name=candidate.person_name,
        )
        if not raw_title:
            results[idx] = candidate
        else:
            pending.append((idx, candidate, extracted, raw_title))
        if profile_delay > 0:
            time.sleep(profile_delay)

    verified: dict[str, str] = {}
    if enable_anthropic and anthropic_key and pending:
        batch_items = [
            {
                "linkedin_url": normalize_profile_url(c.linkedin_in_url),
                "person_name": c.person_name,
                "company_name": c.company_name,
                "current_title": c.person_title,
                "experience_title": extracted.get("experience_title", ""),
                "headline_title": extracted.get("headline_title", ""),
                "proposed_title": raw_title,
                "role_target": c.role_target,
            }
            for _idx, c, extracted, raw_title in pending
        ]
        verified = verify_titles_with_anthropic(
            batch_items,
            api_key=anthropic_key,
            model=anthropic_model,
            timeout=timeout,
        )
        stats.anthropic_verified = len(verified)

    for idx, candidate, _extracted, raw_title in pending:
        url_key = normalize_profile_url(candidate.linkedin_in_url).lower()
        final_title = verified.get(url_key) or raw_title
        if final_title and final_title != (candidate.person_title or "").strip():
            stats.titles_updated += 1
            results[idx] = _with_title(candidate, final_title)
        else:
            results[idx] = candidate

    out = [row for row in results if row is not None]

    _log(
        "LinkedIn title enrichment: "
        f"fetched={stats.profiles_fetched} updated={stats.titles_updated} "
        f"anthropic={stats.anthropic_verified} fetch_failures={stats.fetch_failures}"
    )

    try:
        from gtm.linkedin_scraper.people_discovery.team_pages_playwright import (
            shutdown_playwright,
        )

        shutdown_playwright()
    except Exception:
        pass

    return out, stats
