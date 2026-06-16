"""Team/leadership page discovery and candidate extraction."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from gtm.linkedin_scraper.scrapers.http_client import fetch_url

from .firecrawl_pages import fetch_page_via_firecrawl
from .team_pages_playwright import fetch_page_via_playwright

TEAM_PATHS: tuple[str, ...] = (
    "/team",
    "/leadership",
    "/people",
    "/our-team",
    "/investment-team",
    "/about/team",
)

TEAM_PATHS_MAX_COVERAGE: tuple[str, ...] = TEAM_PATHS + (
    "/about",
    "/about/leadership",
    "/about/people",
    "/management",
    "/investor-relations",
    "/ir",
    "/executive-team",
    "/company/leadership",
    "/about-us/leadership",
    "/about-us/team",
)

PERSON_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$")

LINKEDIN_IN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_%\-\.]+/?",
    re.IGNORECASE,
)

MIN_USEFUL_HTML_LEN = 200


def _origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_urls(base_url: str, *, max_coverage: bool = False) -> list[str]:
    root = _origin(base_url)
    paths = TEAM_PATHS_MAX_COVERAGE if max_coverage else TEAM_PATHS
    return [urljoin(root + "/", p.lstrip("/")) for p in paths]


def _contains_role(text: str, role_variations: list[str]) -> bool:
    low = (text or "").lower()
    return any(r.lower() in low for r in role_variations)


def _fetch_page_content(
    url: str,
    *,
    timeout: float,
    firecrawl_api_key: str | None = None,
    enable_playwright: bool = False,
) -> str | None:
    """httpx → Firecrawl → Playwright (max coverage)."""
    html = fetch_url(url, timeout=timeout)
    if html and len(html.strip()) >= MIN_USEFUL_HTML_LEN:
        return html

    if firecrawl_api_key:
        scraped = fetch_page_via_firecrawl(
            url,
            api_key=firecrawl_api_key,
            timeout=max(float(timeout), 30.0),
        )
        if scraped and len(scraped.strip()) >= MIN_USEFUL_HTML_LEN:
            return scraped

    if enable_playwright:
        pw_html = fetch_page_via_playwright(url, timeout=max(float(timeout), 30.0))
        if pw_html and len(pw_html.strip()) >= MIN_USEFUL_HTML_LEN:
            return pw_html

    return html


def extract_team_people(
    *,
    website: str,
    role_variations: list[str],
    timeout: float = 15.0,
    firecrawl_api_key: str | None = None,
    enable_playwright: bool = False,
    max_coverage: bool = False,
) -> list[tuple[str, str]]:
    """
    Return (person_name, person_title) tuples that match target roles.
    """
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for url in _build_urls(website, max_coverage=max_coverage):
        content = _fetch_page_content(
            url,
            timeout=timeout,
            firecrawl_api_key=firecrawl_api_key,
            enable_playwright=enable_playwright,
        )
        if not content:
            continue
        soup = BeautifulSoup(content, "lxml")
        blocks = soup.find_all(["article", "li", "div", "section"])
        for block in blocks:
            text = " ".join(block.stripped_strings)
            if not text or len(text) < 8:
                continue
            if not _contains_role(text, role_variations):
                continue

            lines = [x.strip() for x in block.get_text("\n", strip=True).split("\n") if x.strip()]
            if not lines:
                continue
            name = ""
            title = ""
            for line in lines[:4]:
                if not name and PERSON_NAME_RE.match(line):
                    name = line
                    continue
                if not title and _contains_role(line, role_variations):
                    title = line
            if not title:
                title = lines[0][:120]
            if not name:
                maybe_name = lines[0].split("|")[0].split(",")[0].strip()
                if PERSON_NAME_RE.match(maybe_name):
                    name = maybe_name
            if not name:
                continue
            pair = (name, title)
            if pair in seen:
                continue
            seen.add(pair)
            found.append(pair)
    return found


def extract_team_linkedin_profiles(
    *,
    website: str,
    role_variations: list[str],
    timeout: float = 15.0,
    firecrawl_api_key: str | None = None,
    enable_playwright: bool = False,
    max_coverage: bool = False,
) -> list[tuple[str, str, str]]:
    """
    Return (linkedin_in_url, person_name, person_title) from team page anchors.
    """
    from .candidate_extract import normalize_profile_url

    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for page_url in _build_urls(website):
        content = _fetch_page_content(
            page_url,
            timeout=timeout,
            firecrawl_api_key=firecrawl_api_key,
        )
        if not content:
            continue
        soup = BeautifulSoup(content, "lxml")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "linkedin.com/in/" not in href.lower():
                continue
            match = LINKEDIN_IN_RE.search(href)
            if not match:
                continue
            profile_url = normalize_profile_url(match.group(0))
            if not profile_url:
                continue
            key = profile_url.lower()
            if key in seen:
                continue
            block_text = ""
            parent = anchor.parent
            for _ in range(4):
                if parent is None:
                    break
                block_text = parent.get_text(" ", strip=True)
                if len(block_text) > 20:
                    break
                parent = parent.parent
            if role_variations and not max_coverage and not _contains_role(block_text, role_variations):
                continue
            name = anchor.get_text(strip=True) or ""
            title = block_text[:120] if block_text else ""
            seen.add(key)
            found.append((profile_url, name, title))

        for match in LINKEDIN_IN_RE.findall(content):
            profile_url = normalize_profile_url(match)
            if not profile_url:
                continue
            key = profile_url.lower()
            if key in seen:
                continue
            blob_start = max(0, content.find(match) - 200)
            blob = content[blob_start : blob_start + 400]
            if role_variations and not max_coverage and not _contains_role(blob, role_variations):
                continue
            lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
            name = lines[0][:80] if lines else ""
            title = lines[1][:120] if len(lines) > 1 else ""
            seen.add(key)
            found.append((profile_url, name, title))
    return found
