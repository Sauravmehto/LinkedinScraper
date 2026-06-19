"""Orchestrate final HubSpot import report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gtm.linkedin_scraper.config import load_fallback_config
from gtm.linkedin_scraper.io_utils import DATA_DIR, OUTPUT_DIR

from gtm.linkedin_scraper.people_discovery.candidate_cap import (
    DEFAULT_MAX_PER_COMPANY,
    cap_candidates_per_company,
)

from .anthropic_report import build_final_rows
from .hubspot_data_template import HUBSPOT_DATA_TEMPLATE, load_template_headers
from .merge import FinalReportStats, merge_and_filter_people
from .writer import write_hubspot_data_report

DEFAULT_TEMPLATE = OUTPUT_DIR / "Hubspot CD 20052026 1.xlsx"
FALLBACK_TEMPLATE = DATA_DIR / "Hubspot CD 20052026 1.xlsx"
GTM_FINAL_TEMPLATE = DATA_DIR / "GTM_Final_File.xlsx"
DEFAULT_OUTPUT = OUTPUT_DIR / "final_report.xlsx"
GTM_FINAL_REPORT_OUTPUT = DEFAULT_OUTPUT


def resolve_template_path(path: Path | None) -> Path:
    if path is not None:
        return path
    if HUBSPOT_DATA_TEMPLATE.exists():
        return HUBSPOT_DATA_TEMPLATE
    if GTM_FINAL_TEMPLATE.exists():
        return GTM_FINAL_TEMPLATE
    if DEFAULT_TEMPLATE.exists():
        return DEFAULT_TEMPLATE
    if FALLBACK_TEMPLATE.exists():
        return FALLBACK_TEMPLATE
    return HUBSPOT_DATA_TEMPLATE


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
    use_anthropic: bool = True,
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

    if dry_run:
        _log(
            f"Final report: rows_in={stats.rows_in} after_filter={stats.after_filter} "
            f"written={stats.written} (dry run)"
        )
        return stats

    headers = load_template_headers(template_path)
    cfg = load_fallback_config()
    anthropic_key = cfg.anthropic_api_key if use_anthropic else None
    if use_anthropic and not anthropic_key:
        _log("Anthropic final report: skipped (no ANTHROPIC_API_KEY); using deterministic mapping")

    row_dicts, method = build_final_rows(
        candidates,
        companies_by_name,
        headers=headers,
        api_key=anthropic_key,
        model=cfg.anthropic_model or "claude-sonnet-4-5-20250929",
        use_anthropic=bool(use_anthropic and anthropic_key),
        log=_log,
    )
    stats.written = len(row_dicts)

    write_hubspot_data_report(template_path, output_path, headers, row_dicts)

    _log(
        f"Final report ({method}): rows_in={stats.rows_in} after_filter={stats.after_filter} "
        f"written={stats.written} "
        f"skipped(linkedin={stats.skipped_no_linkedin} score={stats.skipped_low_score} "
        f"email={stats.skipped_no_email} phone={stats.skipped_no_phone}) "
        f"deduped(linkedin={stats.deduped_by_linkedin} email={stats.deduped_by_email})"
    )
    _log(f"Saved {output_path}")

    return stats
