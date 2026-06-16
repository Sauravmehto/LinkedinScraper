"""Step 5 fallback: Brave Search API."""

from __future__ import annotations

from .common import company_query, extract_company_urls, fetch_text, url_encode_query
from .types import LinkedInCandidate


def search(
    company: str,
    website: str,
    *,
    api_key: str | None,
    timeout: float = 15.0,
) -> list[LinkedInCandidate]:
    if not api_key:
        return []

    query = company_query(company, website)
    url = f"https://api.search.brave.com/res/v1/web/search?q={url_encode_query(query)}&count=10"
    text = fetch_text(
        url,
        timeout=timeout,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    if not text:
        return []

    urls = extract_company_urls(text)
    return [
        LinkedInCandidate(
            url=u,
            source="brave",
            confidence=0.86 - (i * 0.01),
            reason="brave web api",
        )
        for i, u in enumerate(urls[:5])
    ]
