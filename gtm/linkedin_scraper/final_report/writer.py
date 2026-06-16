"""Write final_report.xlsx from HubSpot CD template + merged contacts."""

from __future__ import annotations

import shutil
from pathlib import Path
from openpyxl import load_workbook

from gtm.linkedin_scraper.hubspot_sync.mapper import CompanyRow
from gtm.linkedin_scraper.people_discovery.types import PersonCandidate

from .template_map import ReportDefaults, build_row_values, resolve_company_for_candidate


def write_final_report(
    template_path: Path,
    output_path: Path,
    candidates: list[PersonCandidate],
    companies_by_name: dict[str, CompanyRow],
    *,
    defaults: ReportDefaults | None = None,
    dry_run: bool = False,
) -> None:
    if dry_run:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)

    try:
        wb = load_workbook(output_path)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot open {output_path}. Close Excel and retry."
        ) from exc

    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    for candidate in candidates:
        company = resolve_company_for_candidate(candidate, companies_by_name)
        row_values = build_row_values(
            headers,
            candidate,
            company=company,
            defaults=defaults,
        )
        ws.append(row_values)

    try:
        wb.save(output_path)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot save {output_path}. Close Excel and retry."
        ) from exc
    finally:
        wb.close()
