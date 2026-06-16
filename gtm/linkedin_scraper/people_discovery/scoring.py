"""Deterministic relevance scoring for decision-maker candidates."""

from __future__ import annotations

import re

from .candidate_extract import normalize_person_name
from .types import Confidence

SENIORITY_KEYWORDS = (
    "chief",
    "cfo",
    "coo",
    "cio",
    "cto",
    "director",
    "managing director",
    "partner",
    "principal",
    "head of",
    "vp",
)

FINANCE_KEYWORDS = ("fund", "portfolio", "aum", "private equity", "investment", "reit", "hedge")

FORMER_SIGNALS = ("former", "ex-", "previously", "formerly")


def _contains_any(text: str, words: list[str] | tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(w.lower() in low for w in words)


def score_candidate(
    *,
    company_name: str,
    role_variations: list[str],
    title_text: str,
    snippet_text: str,
    person_name: str = "",
    work_email: str = "",
) -> int:
    score = 0
    title_low = (title_text or "").lower()
    snippet_low = (snippet_text or "").lower()
    company_low = (company_name or "").lower()

    if company_low and company_low in title_low:
        score += 30
    if company_low and company_low in snippet_low:
        score += 20

    if role_variations:
        exact = role_variations[0].lower()
        if exact in title_low:
            score += 30
        elif _contains_any(title_low, role_variations) or _contains_any(snippet_low, role_variations):
            score += 20

    if _contains_any(title_low, SENIORITY_KEYWORDS):
        score += 15
    if _contains_any(snippet_low, FINANCE_KEYWORDS):
        score += 10

    if " at " in snippet_low or "current" in snippet_low:
        score += 10

    if _contains_any(snippet_low, FORMER_SIGNALS) or _contains_any(title_low, FORMER_SIGNALS):
        score -= 20

    if (work_email or "").strip() and "@" in work_email:
        score += 15

    norm_name = normalize_person_name(person_name)
    if norm_name and len(norm_name.split()) >= 2:
        score += 10

    return max(0, min(100, score))


def confidence_from_score(score: int) -> Confidence:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"
