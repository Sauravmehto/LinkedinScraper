"""Step 8 fallback: Tavily API search."""

from __future__ import annotations

from .common import company_query, extract_company_urls, post_json
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

    payload = {
        "api_key": api_key,
        "query": company_query(company, website),
        "search_depth": "basic",
        "max_results": 5,
    }
    data = post_json("https://api.tavily.com/search", payload, timeout=timeout)
    if not data:
        return []

    text_parts: list[str] = []
    for item in data.get("results", []):
        if isinstance(item, dict):
            text_parts.append(str(item.get("url", "")))
            text_parts.append(str(item.get("content", "")))
            text_parts.append(str(item.get("title", "")))
    urls = extract_company_urls("\n".join(text_parts))
    return [
        LinkedInCandidate(
            url=u,
            source="tavily",
            confidence=0.78 - (i * 0.01),
            reason="tavily api result",
        )
        for i, u in enumerate(urls[:5])
    ]
