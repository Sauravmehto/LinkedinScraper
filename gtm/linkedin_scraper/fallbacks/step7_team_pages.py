"""Step 7 fallback: targeted same-site team/about/people pages."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from gtm.linkedin_scraper.scrapers.http_client import fetch_url
from gtm.linkedin_scraper.scrapers.linkedin_extract import extract_deep_from_page

from .types import LinkedInCandidate

TEAM_PATHS: tuple[str, ...] = (
    "/team",
    "/our-team",
    "/leadership",
    "/people",
    "/company/leadership",
    "/about/team",
    "/about/people",
)


def _team_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return [urljoin(origin + "/", p.lstrip("/")) for p in TEAM_PATHS]


def search(base_url: str, timeout: float = 15.0) -> list[LinkedInCandidate]:
    out: list[LinkedInCandidate] = []
    for idx, url in enumerate(_team_urls(base_url)):
        html = fetch_url(url, timeout=timeout)
        if not html:
            continue
        found = extract_deep_from_page(html, url)
        if not found:
            continue
        out.append(
            LinkedInCandidate(
                url=found,
                source="team_pages",
                confidence=0.84 - (idx * 0.01),
                reason=f"team page path {urlparse(url).path}",
            )
        )
    return out
