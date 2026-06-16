"""Cap decision-maker lists per company by score."""

from __future__ import annotations

from collections import defaultdict

from .candidate_extract import normalize_profile_url
from .types import PersonCandidate

DEFAULT_MAX_PER_COMPANY = 15


def cap_candidates_per_company(
    candidates: list[PersonCandidate],
    *,
    max_per_company: int = DEFAULT_MAX_PER_COMPANY,
) -> list[PersonCandidate]:
    """Keep up to N unique LinkedIn profiles per company, highest score first."""
    if max_per_company <= 0:
        return candidates

    by_company: dict[str, list[PersonCandidate]] = defaultdict(list)
    for candidate in candidates:
        company = (candidate.company_name or "").strip()
        if not company:
            continue
        by_company[company].append(candidate)

    selected: list[PersonCandidate] = []
    for company in sorted(by_company.keys(), key=str.casefold):
        rows = by_company[company]
        rows.sort(key=lambda c: (-c.score, (c.person_name or "").casefold()))
        seen_urls: set[str] = set()
        for candidate in rows:
            url_key = normalize_profile_url(candidate.linkedin_in_url).lower()
            if not url_key or url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            selected.append(candidate)
            if len(seen_urls) >= max_per_company:
                break
    return selected
