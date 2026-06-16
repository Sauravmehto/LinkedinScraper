"""Step 6 fallback: DuckDuckGo HTML search."""

from __future__ import annotations

from .common import company_query, extract_company_urls, fetch_text, url_encode_query
from .types import LinkedInCandidate


def search(company: str, website: str, timeout: float = 15.0) -> list[LinkedInCandidate]:
    query = company_query(company, website)
    url = f"https://duckduckgo.com/html/?q={url_encode_query(query)}"
    html = fetch_text(url, timeout=timeout)
    if not html:
        return []
    urls = extract_company_urls(html)
    return [
        LinkedInCandidate(
            url=u,
            source="ddg",
            confidence=0.76 - (i * 0.01),
            reason="duckduckgo html search",
        )
        for i, u in enumerate(urls[:5])
    ]
