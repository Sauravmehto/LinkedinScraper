"""Step 9 fallback: Apollo API (last resort)."""

from __future__ import annotations

from .common import extract_company_urls, post_json
from .types import LinkedInCandidate


def search(
    company: str,
    *,
    api_key: str | None,
    timeout: float = 15.0,
) -> list[LinkedInCandidate]:
    """
    Try Apollo organization search endpoint.

    Apollo API surface can vary by account plan; failures are treated as no-result.
    """
    if not api_key:
        return []

    payload = {"q_organization_name": company, "page": 1, "per_page": 5}
    data = post_json(
        "https://api.apollo.io/api/v1/mixed_people/api_search",
        payload,
        timeout=timeout,
        headers={
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    if not data:
        return []

    text_parts: list[str] = [str(data)]
    urls = extract_company_urls("\n".join(text_parts))
    return [
        LinkedInCandidate(
            url=u,
            source="apollo",
            confidence=0.74 - (i * 0.01),
            reason="apollo api match",
        )
        for i, u in enumerate(urls[:5])
    ]
