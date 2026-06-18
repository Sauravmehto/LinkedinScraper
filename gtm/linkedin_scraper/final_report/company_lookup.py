"""Resolve company rows for final report when names do not match exactly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from gtm.linkedin_scraper.hubspot_sync.client import domain_from_website
from gtm.linkedin_scraper.hubspot_sync.mapper import CompanyRow
from gtm.linkedin_scraper.people_discovery.candidate_extract import normalize_profile_url

_NAME_SUFFIXES = (
    " asset management",
    " investment management",
    " real estate",
    " realty",
    " partners",
    " capital",
    " group",
    " holdings",
    " corporation",
    " incorporated",
    " company",
    " llc",
    " llp",
    " lp",
    " ltd",
    " inc",
    " co",
    " corp",
)


def _company_key(name: str) -> str:
    return (name or "").strip().casefold()


def _normalize_company_name(name: str) -> str:
    text = (name or "").strip().casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed and text:
        changed = False
        for suffix in _NAME_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)].strip()
                changed = True
                break
    return text


def _linkedin_company_key(url: str) -> str:
    normalized = normalize_profile_url(url).casefold()
    if "/company/" not in normalized:
        return ""
    slug = normalized.split("/company/", 1)[-1].split("/")[0].split("?")[0].strip()
    return slug


@dataclass
class CompanyIndexes:
    by_exact: dict[str, CompanyRow] = field(default_factory=dict)
    by_norm: dict[str, CompanyRow] = field(default_factory=dict)
    by_domain: dict[str, CompanyRow] = field(default_factory=dict)
    by_linkedin: dict[str, CompanyRow] = field(default_factory=dict)
    rows: list[CompanyRow] = field(default_factory=list)


def build_company_indexes(rows: list[CompanyRow]) -> CompanyIndexes:
    indexes = CompanyIndexes(rows=list(rows))
    for row in rows:
        exact = _company_key(row.name)
        if exact:
            indexes.by_exact[exact] = row

        norm = _normalize_company_name(row.name)
        if norm:
            indexes.by_norm.setdefault(norm, row)

        domain = domain_from_website(row.website)
        if domain:
            indexes.by_domain.setdefault(domain, row)

        li_key = _linkedin_company_key(row.company_linkedin)
        if li_key:
            indexes.by_linkedin.setdefault(li_key, row)
    return indexes


def lookup_company(
    *,
    company_name: str,
    company_website: str = "",
    company_linkedin: str = "",
    indexes: CompanyIndexes,
) -> CompanyRow | None:
    exact = _company_key(company_name)
    if exact and exact in indexes.by_exact:
        return indexes.by_exact[exact]

    norm = _normalize_company_name(company_name)
    if norm and norm in indexes.by_norm:
        return indexes.by_norm[norm]

    domain = domain_from_website(company_website)
    if domain and domain in indexes.by_domain:
        return indexes.by_domain[domain]

    li_key = _linkedin_company_key(company_linkedin)
    if li_key and li_key in indexes.by_linkedin:
        return indexes.by_linkedin[li_key]

    if norm and len(norm) >= 4:
        best: CompanyRow | None = None
        best_len = 0
        for stored_norm, row in indexes.by_norm.items():
            if norm in stored_norm or stored_norm in norm:
                match_len = min(len(norm), len(stored_norm))
                if match_len > best_len:
                    best = row
                    best_len = match_len
        if best is not None:
            return best

    return None
