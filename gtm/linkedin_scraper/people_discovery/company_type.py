"""Company type classification heuristics for decision-maker discovery."""

from __future__ import annotations

import re

from .types import CompanyType

TYPE_KEYWORDS: dict[CompanyType, tuple[str, ...]] = {
    "PE": ("private equity", "buyout", "growth equity", "middle market", "pe firm"),
    "REIT": ("reit", "real estate investment trust", "real estate trust"),
    "HEDGE_FUND": ("hedge fund", "alternative investments", "liquid alternatives"),
    "VC": ("venture capital", "seed fund", "series a", "startup investment"),
    "FAMILY_OFFICE": ("family office", "single family office", "multi-family office"),
    "UNKNOWN": (),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify_company_type(
    *,
    company_name: str,
    website_text: str = "",
    override: str | None = None,
) -> CompanyType:
    if override:
        manual = _norm(override).replace("-", "_").replace(" ", "_").upper()
        if manual in {"PE", "REIT", "HEDGE_FUND", "VC", "FAMILY_OFFICE", "UNKNOWN"}:
            return manual  # type: ignore[return-value]

    corpus = f"{_norm(company_name)} {_norm(website_text)}"
    for company_type in ("REIT", "PE", "VC", "HEDGE_FUND", "FAMILY_OFFICE"):
        for kw in TYPE_KEYWORDS[company_type]:
            if kw in corpus:
                return company_type  # type: ignore[return-value]
    return "UNKNOWN"
