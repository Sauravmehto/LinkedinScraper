"""Step 4 fallback: scrape Bing search results for LinkedIn company URLs."""

from __future__ import annotations

from .common import company_query, extract_company_urls, fetch_text, url_encode_query
from .types import LinkedInCandidate


def search(company: str, website: str, timeout: float = 15.0) -> list[LinkedInCandidate]:
    query = company_query(company, website)
    url = f"https://www.bing.com/search?q={url_encode_query(query)}"
    html = fetch_text(url, timeout=timeout)
    if not html:
        return []
    urls = extract_company_urls(html)
    return [
        LinkedInCandidate(
            url=u,
            source="bing",
            confidence=0.80 - (i * 0.01),
            reason="bing search result",
        )
        for i, u in enumerate(urls[:5])
    ]
