"""Company name matching for search-result profile hits."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_STOPWORDS = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "company",
        "co",
        "the",
        "and",
        "of",
        "group",
        "holdings",
        "management",
        "capital",
        "partners",
        "investment",
        "investments",
        "global",
        "international",
    }
)


def company_name_tokens(company_name: str, website: str = "") -> list[str]:
    """Significant tokens for fuzzy company matching in SERP snippets."""
    tokens: set[str] = set()
    for raw in (company_name,):
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (raw or "").lower())
        for part in cleaned.split():
            if len(part) >= 3 and part not in _STOPWORDS:
                tokens.add(part)

    domain = (website or "").strip()
    if domain and not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    host = urlparse(domain).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host:
        base = host.split(".")[0]
        if len(base) >= 3 and base not in _STOPWORDS:
            tokens.add(base)

    return sorted(tokens)


def company_mentioned_in_blob(
    blob: str,
    company_name: str,
    *,
    website: str = "",
) -> bool:
    """True when full name or a significant company token appears in text."""
    low = (blob or "").lower()
    company_low = (company_name or "").lower().strip()
    if not company_low:
        return True
    if company_low in low:
        return True
    for token in company_name_tokens(company_name, website):
        if token in low:
            return True
    return False
