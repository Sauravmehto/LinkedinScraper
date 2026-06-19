"""Orchestrate Phase 3 contact enrichment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..types import PersonCandidate
from .apollo_contacts import enrich_list_via_apollo
from .company_hq import backfill_hq_phones


@dataclass
class EnrichmentStats:
    candidates_in: int = 0
    candidates_out: int = 0
    apollo_calls: int = 0
    with_work_email: int = 0
    with_personal_email: int = 0
    with_direct_dial: int = 0
    with_hq_phone: int = 0
    by_company: dict[str, int] = field(default_factory=dict)

    def summarize(self, candidates: list[PersonCandidate]) -> None:
        self.candidates_out = len(candidates)
        self.with_work_email = sum(1 for c in candidates if (c.work_email or "").strip())
        self.with_personal_email = sum(
            1 for c in candidates if (c.personal_email or "").strip()
        )
        self.with_direct_dial = sum(1 for c in candidates if (c.direct_dial or "").strip())
        self.with_hq_phone = sum(1 for c in candidates if (c.hq_phone or "").strip())


def _attach_company_websites(
    candidates: list[PersonCandidate],
    websites_by_company: dict[str, str],
) -> list[PersonCandidate]:
    if not websites_by_company:
        return candidates
    out: list[PersonCandidate] = []
    for c in candidates:
        site = (c.company_website or "").strip()
        if not site:
            site = websites_by_company.get(c.company_name.strip(), "")
        if site == (c.company_website or "").strip():
            out.append(c)
            continue
        out.append(
            PersonCandidate(
                company_name=c.company_name,
                company_type=c.company_type,
                company_linkedin=c.company_linkedin,
                company_website=site,
                role_target=c.role_target,
                person_name=c.person_name,
                person_title=c.person_title,
                linkedin_in_url=c.linkedin_in_url,
                source=c.source,
                snippet=c.snippet,
                score=c.score,
                confidence=c.confidence,
                notes=c.notes,
                work_email=c.work_email,
                personal_email=c.personal_email,
                email_status=c.email_status,
                email_confidence=c.email_confidence,
                direct_dial=c.direct_dial,
                hq_phone=c.hq_phone,
                ir_email=c.ir_email,
                ir_phone=c.ir_phone,
                phone_source=c.phone_source,
                phone_status=c.phone_status,
                city=c.city,
                state=c.state,
                country=c.country,
            )
        )
    return out


def enrich_candidates(
    candidates: list[PersonCandidate],
    *,
    api_key: str | None,
    timeout: float = 15.0,
    only_missing: bool = True,
    apollo_delay: float = 0.5,
    reveal_phone_number: bool = True,
    reveal_personal_emails: bool = True,
    websites_by_company: dict[str, str] | None = None,
    company_hq_by_name: dict[str, str] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], EnrichmentStats]:
    """
    Phase 3 (Sprint 1–2): Apollo phones + match-by-LinkedIn for missing contacts.
    """
    _log = log or (lambda _msg: None)
    stats = EnrichmentStats(candidates_in=len(candidates))

    enriched = _attach_company_websites(candidates, websites_by_company or {})

    if not api_key:
        _log("Contact enrichment: skipped (no APOLLO_API_KEY)")
        stats.summarize(enriched)
        return enriched, stats

    _log(
        f"Contact enrichment: {len(enriched)} candidate(s), "
        f"only_missing={only_missing}, apollo_delay={apollo_delay}s"
    )
    enriched, apollo_calls, _cache = enrich_list_via_apollo(
        enriched,
        api_key=api_key,
        timeout=timeout,
        only_missing=only_missing,
        reveal_phone_number=reveal_phone_number,
        reveal_personal_emails=reveal_personal_emails,
        match_delay=apollo_delay,
        log=_log,
    )
    stats.apollo_calls = apollo_calls

    enriched, _hq_filled = backfill_hq_phones(
        enriched,
        websites_by_company=websites_by_company,
        company_hq_by_name=company_hq_by_name,
        api_key=api_key,
        timeout=timeout,
        log=_log,
    )

    stats.summarize(enriched)
    _log(
        f"Contact enrichment done: work_email={stats.with_work_email} "
        f"personal_email={stats.with_personal_email} "
        f"direct_dial={stats.with_direct_dial} hq_phone={stats.with_hq_phone} "
        f"apollo_calls={stats.apollo_calls}"
    )
    return enriched, stats
