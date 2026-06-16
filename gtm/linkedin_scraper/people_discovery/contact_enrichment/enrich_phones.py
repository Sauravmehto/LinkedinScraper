"""Orchestrate Apollo async phone enrichment into decision-maker Excel."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..candidate_extract import normalize_profile_url
from ..types import PersonCandidate
from .apollo_phone_store import record_job, save_result, update_job_status
from .apollo_phones_async import reveal_and_poll_phones
from .people_excel import read_people_workbook, write_people_workbook


@dataclass
class PhoneEnrichmentStats:
    rows_in: int = 0
    eligible: int = 0
    skipped_has_phone: int = 0
    skipped_no_linkedin: int = 0
    submitted: int = 0
    phones_received: int = 0
    timeout: int = 0
    errors: int = 0


def _linkedin_key(url: str) -> str:
    return normalize_profile_url(url).lower()


def enrich_phones_in_workbook(
    input_path: Path,
    output_path: Path,
    *,
    api_key: str,
    webhook_url: str,
    sheet: str | None = None,
    only_missing: bool = True,
    poll: bool = True,
    poll_timeout: float = 120.0,
    poll_interval: float = 5.0,
    submit_delay: float = 0.5,
    request_timeout: float = 30.0,
    limit: int = 0,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> tuple[list[PersonCandidate], PhoneEnrichmentStats]:
    _log = log or (lambda _m: None)
    stats = PhoneEnrichmentStats()

    candidates = read_people_workbook(input_path, sheet=sheet)
    stats.rows_in = len(candidates)

    to_enrich: list[PersonCandidate] = []
    for candidate in candidates:
        if only_missing and (candidate.direct_dial or "").strip():
            stats.skipped_has_phone += 1
            continue
        key = _linkedin_key(candidate.linkedin_in_url)
        if not key or "/in/" not in key:
            stats.skipped_no_linkedin += 1
            continue
        to_enrich.append(candidate)

    stats.eligible = len(to_enrich)
    if limit > 0:
        to_enrich = to_enrich[:limit]

    updates: dict[str, PersonCandidate] = {}

    if not webhook_url and not dry_run:
        _log("Missing APOLLO_WEBHOOK_URL — set in .env or pass --webhook-url")
        return candidates, stats

    for candidate in to_enrich:
        key = _linkedin_key(candidate.linkedin_in_url)

        if dry_run:
            _log(f"[dry-run] phone reveal: {candidate.person_name} @ {candidate.company_name}")
            stats.submitted += 1
            continue

        if not poll:
            _log("--no-poll: submit-only not implemented; use default --poll")
            continue

        updated, result = reveal_and_poll_phones(
            candidate,
            api_key=api_key,
            webhook_url=webhook_url,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
            request_timeout=request_timeout,
            submit_delay=submit_delay,
            log=_log,
        )
        stats.submitted += 1
        updates[key] = updated

        if result and result.request_id:
            record_job(
                linkedin_key=key,
                request_id=result.request_id,
                work_email=candidate.work_email,
                person_name=candidate.person_name,
                status=result.phone_status,
            )
            save_result(
                result.request_id,
                {
                    "request_id": result.request_id,
                    "person": result.person,
                    "status": result.phone_status,
                },
            )

        if (updated.direct_dial or "").strip():
            stats.phones_received += 1
            update_job_status(key, "received")
        elif updated.phone_status == "timeout":
            stats.timeout += 1
            update_job_status(key, "timeout")
        elif updated.phone_status in ("submit_error", "no_request_id"):
            stats.errors += 1

    final: list[PersonCandidate] = []
    for candidate in candidates:
        key = _linkedin_key(candidate.linkedin_in_url)
        final.append(updates.get(key, candidate))

    _log(
        f"Phone enrichment: eligible={stats.eligible} submitted={stats.submitted} "
        f"received={stats.phones_received} timeout={stats.timeout} "
        f"skipped_has_phone={stats.skipped_has_phone} errors={stats.errors}"
    )

    if not dry_run:
        write_people_workbook(output_path, final)

    return final, stats
