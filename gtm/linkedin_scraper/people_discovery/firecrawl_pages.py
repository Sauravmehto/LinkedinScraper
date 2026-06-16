"""Firecrawl API fallback for JS-heavy team/leadership pages."""

from __future__ import annotations

import httpx

from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"


def fetch_page_via_firecrawl(
    url: str,
    *,
    api_key: str,
    timeout: float = 30.0,
) -> str | None:
    """
    Scrape a single URL via Firecrawl and return HTML (preferred) or markdown.
    Returns None on API/network errors or empty content.
    """
    if not api_key or not url:
        return None
    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS) as client:
            resp = client.post(
                FIRECRAWL_SCRAPE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["html", "markdown"],
                    "onlyMainContent": True,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        return None

    if isinstance(payload, dict) and payload.get("success") is False:
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}

    html = str(data.get("html") or "").strip()
    if html:
        return html

    markdown = str(data.get("markdown") or "").strip()
    return markdown or None
