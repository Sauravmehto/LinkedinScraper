"""Join companies + people, filter, and dedupe for final HubSpot report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gtm.linkedin_scraper.hubspot_sync.loaders import load_companies_from_workbook
from gtm.linkedin_scraper.hubspot_sync.mapper import CompanyRow
from gtm.linkedin_scraper.people_discovery.candidate_extract import (
    is_valid_profile_url,
    normalize_profile_url,
)
from gtm.linkedin_scraper.people_discovery.contact_enrichment.people_excel import (
    read_people_workbook,
)
from gtm.linkedin_scraper.people_discovery.candidate_cap import (
    DEFAULT_MAX_PER_COMPANY,
    cap_candidates_per_company,
)
from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

from .company_lookup import CompanyIndexes, build_company_indexes, lookup_company


def _company_key(name: str) -> str:
    return (name or "").strip().casefold()


def enrich_person(
    candidate: PersonCandidate,
    company: CompanyRow | None,
) -> PersonCandidate:
    if company is None:
        return candidate
    website = (candidate.company_website or "").strip() or (company.website or "").strip()
    linkedin = (candidate.company_linkedin or "").strip() or (
        company.company_linkedin or ""
    ).strip()
    hq = (candidate.hq_phone or "").strip() or (company.hq_phone or "").strip()
    return PersonCandidate(
        company_name=candidate.company_name,
        company_type=candidate.company_type,
        company_linkedin=linkedin,
        company_website=website,
        role_target=candidate.role_target,
        person_name=candidate.person_name,
        person_title=candidate.person_title,
        linkedin_in_url=candidate.linkedin_in_url,
        source=candidate.source,
        snippet=candidate.snippet,
        score=candidate.score,
        confidence=candidate.confidence,
        notes=candidate.notes,
        work_email=candidate.work_email,
        personal_email=candidate.personal_email,
        email_status=candidate.email_status,
        email_confidence=candidate.email_confidence,
        direct_dial=candidate.direct_dial,
        hq_phone=hq,
        ir_email=candidate.ir_email,
        ir_phone=candidate.ir_phone,
        phone_source=candidate.phone_source,
        phone_status=candidate.phone_status,
        city=candidate.city,
        state=candidate.state,
        country=candidate.country,
    )


@dataclass
class FinalReportStats:
    rows_in: int = 0
    skipped_no_linkedin: int = 0
    skipped_low_score: int = 0
    skipped_no_email: int = 0
    skipped_no_phone: int = 0
    after_filter: int = 0
    deduped_by_linkedin: int = 0
    deduped_by_email: int = 0
    written: int = 0


def _dedupe_by_key(
    candidates: list[PersonCandidate],
    key_fn,
    *,
    skip_empty_key: bool = True,
) -> tuple[list[PersonCandidate], int]:
    best: dict[str, PersonCandidate] = {}
    no_key: list[PersonCandidate] = []
    removed = 0
    for candidate in candidates:
        key = key_fn(candidate)
        if not key:
            if skip_empty_key:
                no_key.append(candidate)
            continue
        existing = best.get(key)
        if existing is None:
            best[key] = candidate
        else:
            removed += 1
            if candidate.score > existing.score:
                best[key] = candidate
    return list(best.values()) + no_key, removed


def merge_and_filter_people(
    people_path: Path,
    companies_path: Path | None,
    *,
    min_score: int = 55,
    require_email: bool = True,
    require_phone: bool = False,
    people_sheet: str | None = None,
    companies_sheet: str | None = None,
    max_per_company: int = DEFAULT_MAX_PER_COMPANY,
) -> tuple[list[PersonCandidate], dict[str, CompanyRow], FinalReportStats]:
    stats = FinalReportStats()
    company_rows: list[CompanyRow] = []
    companies_by_name: dict[str, CompanyRow] = {}
    if companies_path and companies_path.exists():
        company_rows = load_companies_from_workbook(companies_path, sheet=companies_sheet)
        for row in company_rows:
            companies_by_name[_company_key(row.name)] = row
    company_indexes = build_company_indexes(company_rows)

    people = read_people_workbook(people_path, sheet=people_sheet)
    stats.rows_in = len(people)

    filtered: list[PersonCandidate] = []
    for raw in people:
        linkedin = normalize_profile_url(raw.linkedin_in_url)
        if not linkedin or not is_valid_profile_url(linkedin):
            stats.skipped_no_linkedin += 1
            continue
        if raw.score < min_score:
            stats.skipped_low_score += 1
            continue
        email = (raw.work_email or raw.personal_email or "").strip()
        if require_email and not email:
            stats.skipped_no_email += 1
            continue
        if require_phone and not (raw.direct_dial or raw.hq_phone or "").strip():
            stats.skipped_no_phone += 1
            continue

        company = lookup_company(
            company_name=raw.company_name,
            company_website=raw.company_website,
            company_linkedin=raw.company_linkedin,
            indexes=company_indexes,
        )
        candidate = enrich_person(
            PersonCandidate(
                company_name=raw.company_name,
                company_type=raw.company_type,
                company_linkedin=raw.company_linkedin,
                company_website=raw.company_website,
                role_target=raw.role_target,
                person_name=raw.person_name,
                person_title=raw.person_title,
                linkedin_in_url=linkedin,
                source=raw.source,
                snippet=raw.snippet,
                score=raw.score,
                confidence=raw.confidence,
                notes=raw.notes,
                work_email=raw.work_email,
                personal_email=raw.personal_email,
                email_status=raw.email_status,
                email_confidence=raw.email_confidence,
                direct_dial=raw.direct_dial,
                hq_phone=raw.hq_phone,
                ir_email=raw.ir_email,
                ir_phone=raw.ir_phone,
                phone_source=raw.phone_source,
                phone_status=raw.phone_status,
                city=raw.city,
                state=raw.state,
                country=raw.country,
            ),
            company,
        )
        filtered.append(candidate)

    stats.after_filter = len(filtered)

    if max_per_company > 0:
        filtered = cap_candidates_per_company(filtered, max_per_company=max_per_company)

    by_linkedin, removed_li = _dedupe_by_key(
        filtered,
        lambda c: normalize_profile_url(c.linkedin_in_url).casefold(),
    )
    stats.deduped_by_linkedin = removed_li

    by_email, removed_em = _dedupe_by_key(
        by_linkedin,
        lambda c: (
            (c.work_email or c.personal_email or "").strip().lower()
        ),
    )
    stats.deduped_by_email = removed_em

    stats.written = len(by_email)
    return by_email, companies_by_name, stats
