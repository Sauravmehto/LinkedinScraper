"""Scrape LinkedIn profile URLs from Official Website column."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from gtm.linkedin_scraper.config import DEFAULT_FALLBACK_STEPS, load_fallback_config
from gtm.linkedin_scraper.fallbacks.linkedin_rules import is_valid_company_url
from gtm.linkedin_scraper.fallbacks.manager import FallbackStats, run_fallback_waterfall
from gtm.linkedin_scraper.io_utils import (
    PROFILE_HEADER,
    SCRAPE_METHOD_HEADER,
    WEBSITE_HEADER,
    LogFn,
    build_scrape_tasks,
    ensure_column,
    find_column_index,
    get_header_row,
    resolve_worksheet,
    write_column_values,
)
from gtm.linkedin_scraper.scrapers.pipeline import (
    scrape_company_website,
    shutdown as shutdown_scrapers,
)

_print_lock = threading.Lock()


def _log(msg: str, log: LogFn) -> None:
    with _print_lock:
        log(msg)


def parse_steps(value: str) -> tuple[int, ...]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return (1,)
    return tuple(int(p) for p in parts)


def result_to_status(result) -> str:
    if result.profile_url:
        return result.profile_url
    if "fetch failed" in result.note:
        return "fetch failed"
    if "no linkedin" in result.note:
        return "no linkedin found"
    if "playwright not installed" in result.note:
        return "playwright not installed"
    return result.note


def process_row(
    row_idx: int,
    company: str,
    website: str,
    steps: tuple[int, ...],
    timeout: float,
    skip_filled: bool,
    existing_profile: Optional[str],
) -> tuple[int, Optional[str], str, str]:
    if skip_filled and existing_profile:
        return row_idx, existing_profile, "skipped (already filled)", ""

    result = scrape_company_website(website, steps=steps, timeout=timeout)
    status = result_to_status(result)
    method = result.method if result.profile_url else ""
    return row_idx, result.profile_url, status, method


@dataclass
class ScrapeStats:
    ok: int = 0
    fail: int = 0
    skip: int = 0


def run_scrape(
    wb: Workbook,
    *,
    sheet: Optional[str] = None,
    steps: tuple[int, ...] = (1, 2),
    workers: int = 25,
    timeout: int = 15,
    force: bool = False,
    skip_filled: bool = True,
    enable_fallbacks: bool = False,
    fallback_steps: tuple[int, ...] = DEFAULT_FALLBACK_STEPS,
    limit: int = 0,
    log: LogFn = print,
) -> tuple[Optional[Worksheet], ScrapeStats]:
    """Scrape LinkedIn URLs into the workbook (in memory). Does not save."""
    ws, sheet_name = resolve_worksheet(wb, sheet, log=log)
    if ws is None:
        return None, ScrapeStats()

    log(f"Scrape [{sheet_name}]")

    headers = get_header_row(ws)
    website_col = find_column_index(headers, WEBSITE_HEADER)
    if website_col is None:
        log(f"Column not found: {WEBSITE_HEADER}")
        return None, ScrapeStats()

    profile_col, created = ensure_column(ws, headers, PROFILE_HEADER)
    if created:
        log(f"Added column: {PROFILE_HEADER}")

    method_col, created_method = ensure_column(ws, headers, SCRAPE_METHOD_HEADER)
    if created_method:
        log(f"Added column: {SCRAPE_METHOD_HEADER}")

    skip = skip_filled and not force
    tasks = build_scrape_tasks(ws, website_col, profile_col, skip_filled=skip)
    if limit > 0:
        tasks = tasks[:limit]

    use_step3 = 3 in steps
    fast_steps = tuple(s for s in steps if s != 3)
    if not fast_steps and not use_step3:
        fast_steps = (1, 2)

    fetch_mode = "httpx+playwright" if use_step3 else "httpx"
    if use_step3:
        log(
            "Step 3 enabled: Playwright runs after Steps 1-2 on remaining rows (main thread). "
            "Install once: python -m pipenv run playwright install chromium"
        )
    log(
        f"Rows to process: {len(tasks)} | workers={workers} | "
        f"steps={','.join(map(str, steps))} | fetch={fetch_mode}"
    )

    results: dict[int, Optional[str]] = {}
    methods: dict[int, str] = {}
    stats = ScrapeStats()
    pending_step3: list[tuple[int, str, str]] = []
    pending_fallbacks: list[tuple[int, str, str]] = []

    def record(
        r_idx: int,
        company: str,
        profile,
        status: str,
        method: str,
        *,
        prefix: str = "",
    ) -> None:
        results[r_idx] = profile
        if method:
            methods[r_idx] = method
        if status.startswith("skipped"):
            stats.skip += 1
        elif profile:
            stats.ok += 1
        else:
            stats.fail += 1
        log(f"{prefix}{company}: {status}")

    if fast_steps:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    process_row,
                    row_idx,
                    company,
                    website,
                    fast_steps,
                    float(timeout),
                    skip,
                    str(existing) if existing else None,
                ): (row_idx, company, website)
                for row_idx, company, website, existing in tasks
            }
            done = 0
            for fut in as_completed(futures):
                row_idx, company, website = futures[fut]
                done += 1
                try:
                    r_idx, profile, status, method = fut.result()
                except Exception as exc:
                    log(f"[{done}/{len(tasks)}] row {row_idx} {company}: error {exc}")
                    stats.fail += 1
                    if use_step3:
                        pending_step3.append((row_idx, company, website))
                    continue

                if use_step3 and not profile and not status.startswith("skipped"):
                    pending_step3.append((row_idx, company, website))

                record(
                    r_idx,
                    company,
                    profile,
                    status,
                    method,
                    prefix=f"[{done}/{len(tasks)}] ",
                )
    elif use_step3:
        for row_idx, company, website, existing in tasks:
            if skip and existing:
                record(row_idx, company, existing, "skipped (already filled)", "")
            else:
                pending_step3.append((row_idx, company, website))

    if use_step3 and pending_step3:
        log(f"Step 3: trying Playwright for {len(pending_step3)} row(s)...")
        for i, (row_idx, company, website) in enumerate(pending_step3, 1):
            result = scrape_company_website(website, steps=(3,), timeout=float(timeout))
            profile = result.profile_url
            if profile and not is_valid_company_url(profile):
                log(
                    f"[step3 {i}/{len(pending_step3)}] {company}: "
                    f"rejected bad LinkedIn URL ({profile}) -> fallback"
                )
                pending_fallbacks.append((row_idx, company, website))
                result = type(result)(profile_url=None, method="not_found", note="bad_url_rejected")
                profile = None
            status = result_to_status(result)
            results[row_idx] = profile
            if profile:
                stats.fail -= 1
                stats.ok += 1
                methods[row_idx] = result.method
            else:
                if not any(row_idx == pf[0] for pf in pending_fallbacks):
                    pending_fallbacks.append((row_idx, company, website))
            log(f"[step3 {i}/{len(pending_step3)}] {company}: {status}")

    if enable_fallbacks:
        if not use_step3:
            log("Fallbacks skipped: Step 3 must be enabled (use --steps 1,2,3).")
        elif pending_fallbacks:
            cfg = load_fallback_config()
            fallback_stats = FallbackStats()
            log(
                f"Fallbacks enabled: trying steps {','.join(map(str, fallback_steps))} "
                f"for {len(pending_fallbacks)} unresolved row(s)"
            )
            for i, (row_idx, company, website) in enumerate(pending_fallbacks, 1):
                fallback = run_fallback_waterfall(
                    company=company,
                    website=website,
                    enabled_steps=fallback_steps,
                    timeout=float(timeout),
                    cfg=cfg,
                    stats=fallback_stats,
                    log=log,
                )
                if fallback.profile_url:
                    results[row_idx] = fallback.profile_url
                    methods[row_idx] = fallback.method
                    stats.fail -= 1
                    stats.ok += 1
                    log(
                        f"[fallback {i}/{len(pending_fallbacks)}] {company}: "
                        f"{fallback.profile_url}"
                    )
                else:
                    log(
                        f"[fallback {i}/{len(pending_fallbacks)}] {company}: no linkedin found"
                    )
            step_counts = " ".join(
                f"step{s}={fallback_stats.by_step.get(s, 0)}" for s in fallback_steps
            )
            log(
                f"Fallback summary: checked={fallback_stats.checked} found={fallback_stats.found} {step_counts}"
            )

    write_column_values(ws, profile_col, results, only_if_value=skip)
    write_column_values(ws, method_col, methods, only_if_value=True)

    log(f"Scrape done. found={stats.ok} missing/failed={stats.fail} skipped={stats.skip}")
    if use_step3:
        shutdown_scrapers()
    return ws, stats
