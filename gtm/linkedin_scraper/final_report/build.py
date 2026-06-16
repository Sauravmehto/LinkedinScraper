"""Orchestrate final HubSpot import report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gtm.linkedin_scraper.io_utils import DATA_DIR, OUTPUT_DIR

from gtm.linkedin_scraper.people_discovery.candidate_cap import (
    DEFAULT_MAX_PER_COMPANY,
    cap_candidates_per_company,
)

from .merge import FinalReportStats, merge_and_filter_people
from .template_map import ReportDefaults
from .writer import write_final_report

DEFAULT_TEMPLATE = OUTPUT_DIR / "Hubspot CD 20052026 1.xlsx"
FALLBACK_TEMPLATE = DATA_DIR / "Hubspot CD 20052026 1.xlsx"
GTM_FINAL_TEMPLATE = DATA_DIR / "GTM_Final_File.xlsx"
DEFAULT_OUTPUT = OUTPUT_DIR / "final_report.xlsx"
GTM_FINAL_REPORT_OUTPUT = DATA_DIR / "GTM_Final_report.xlsx"


def resolve_template_path(path: Path | None) -> Path:
    if path is not None:
        return path
    if GTM_FINAL_TEMPLATE.exists():
        return GTM_FINAL_TEMPLATE
    if DEFAULT_TEMPLATE.exists():
        return DEFAULT_TEMPLATE
    if FALLBACK_TEMPLATE.exists():
        return FALLBACK_TEMPLATE
    return GTM_FINAL_TEMPLATE


def build_final_report(
    *,
    template_path: Path,
    companies_path: Path | None,
    people_path: Path,
    output_path: Path,
    min_score: int = 55,
    require_email: bool = True,
    require_phone: bool = False,
    people_sheet: str | None = None,
    companies_sheet: str | None = None,
    lead_status: str = "",
    lifecycle_stage: str = "lead",
    owner_id: str = "",
    max_per_company: int = DEFAULT_MAX_PER_COMPANY,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> FinalReportStats:
    _log = log or (lambda _m: None)

    candidates, companies_by_name, stats = merge_and_filter_people(
        people_path,
        companies_path,
        min_score=min_score,
        require_email=require_email,
        require_phone=require_phone,
        people_sheet=people_sheet,
        companies_sheet=companies_sheet,
        max_per_company=max_per_company,
    )

    defaults = ReportDefaults(
        lead_status=lead_status,
        lifecycle_stage=lifecycle_stage,
        owner_id=owner_id,
    )

    if not dry_run:
        write_final_report(
            template_path,
            output_path,
            candidates,
            companies_by_name,
            defaults=defaults,
            dry_run=False,
        )

    _log(
        f"Final report: rows_in={stats.rows_in} after_filter={stats.after_filter} "
        f"written={stats.written} "
        f"skipped(linkedin={stats.skipped_no_linkedin} score={stats.skipped_low_score} "
        f"email={stats.skipped_no_email} phone={stats.skipped_no_phone}) "
        f"deduped(linkedin={stats.deduped_by_linkedin} email={stats.deduped_by_email})"
    )
    if dry_run:
        _log("Dry run — workbook not written")
    else:
        _log(f"Saved {output_path}")

    return stats
