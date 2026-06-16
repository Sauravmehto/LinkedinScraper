"""
Scrape pipeline orchestrator.

Runs enabled steps in order and stops at the first LinkedIn URL found.
"""

from __future__ import annotations

from . import step1_html_parse, step2_deep_links, step3_playwright
from .linkedin_extract import normalize_website
from .result import ScrapeResult


def scrape_company_website(
    website: str,
    *,
    steps: tuple[int, ...] = (1, 2),
    timeout: float = 15.0,
) -> ScrapeResult:
    """
    Try each step in *steps* (ascending). Return on first LinkedIn URL found.
    """
    base_url = normalize_website(website)
    if not base_url:
        return ScrapeResult(
            profile_url=None,
            method="not_found",
            note="no website",
        )

    last_note = "no steps ran"
    homepage_html: str | None = None

    if 1 in steps:
        result, homepage_html = step1_html_parse.run(base_url, timeout=timeout)
        if result.profile_url:
            return result
        last_note = result.note

    if 2 in steps:
        result = step2_deep_links.run(
            base_url,
            timeout=timeout,
            homepage_html=homepage_html,
        )
        if result.profile_url:
            return result
        last_note = result.note

    if 3 in steps:
        result = step3_playwright.run(base_url, timeout=timeout)
        if result.profile_url:
            return result
        last_note = result.note

    return ScrapeResult(
        profile_url=None,
        method="not_found",
        note=last_note,
    )


def shutdown() -> None:
    """Release Playwright browser if Step 3 was used."""
    step3_playwright.shutdown_browser()
