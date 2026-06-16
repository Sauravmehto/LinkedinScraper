"""
Step 1 — Fast homepage scrape (free).

When: First attempt for every company row.
What: httpx GET of Official Website + BeautifulSoup/lxml link parse.
Does not: Visit /about or /contact (see step2) or run JavaScript (see step3).
"""

from __future__ import annotations

from .http_client import fetch_url
from .linkedin_extract import extract_linkedin_from_page
from .result import ScrapeResult


def run(base_url: str, timeout: float = 15.0) -> tuple[ScrapeResult, str | None]:
    """
    Returns (result, homepage_html). HTML is passed to Step 2 to avoid a duplicate GET.
    """
    html = fetch_url(base_url, timeout=timeout)
    if not html:
        return (
            ScrapeResult(
                profile_url=None,
                method="not_found",
                note="step1: fetch failed",
            ),
            None,
        )

    profile = extract_linkedin_from_page(html, base_url)
    if profile:
        return (
            ScrapeResult(
                profile_url=profile,
                method="step1",
                note="step1: homepage",
            ),
            html,
        )

    return (
        ScrapeResult(
            profile_url=None,
            method="not_found",
            note="step1: no linkedin on homepage",
        ),
        html,
    )
