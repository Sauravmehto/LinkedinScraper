"""Validate Profile URL column: LinkedIn syntax and live HTTP status."""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from gtm.linkedin_scraper.io_utils import (
    PROFILE_HEADER,
    URL_STATUS_HEADER,
    URL_VALID_HEADER,
    LogFn,
    collect_urls_for_validation,
    ensure_column,
    find_profile_column,
    get_header_row,
    resolve_validation_worksheet,
    write_column_values,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LINKEDIN_RE = re.compile(
    r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[a-zA-Z0-9_%\-\.]+/?$",
    re.IGNORECASE,
)

_print_lock = threading.Lock()


def normalize_profile_url(url: str) -> str:
    url = (url or "").strip()
    return url.rstrip("/").split("?")[0].split("#")[0]


def is_valid_linkedin_syntax(url: str) -> bool:
    if not url:
        return False
    return LINKEDIN_RE.match(normalize_profile_url(url)) is not None


def check_url_live(url: str, timeout: int) -> str:
    normalized = normalize_profile_url(url)
    if not normalized.startswith(("http://", "https://")):
        normalized = "https://" + normalized

    req = urllib.request.Request(
        normalized,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
            final = resp.geturl()
    except urllib.error.HTTPError as exc:
        code = exc.code
        final = exc.geturl() if exc.geturl() else normalized
    except (urllib.error.URLError, TimeoutError, OSError):
        return "timeout"

    if code == 404:
        return "404"
    if code in (403, 999):
        return "blocked"
    if 200 <= code < 300:
        if final and final.rstrip("/") != normalized.rstrip("/"):
            return "OK (redirect)"
        return "OK"
    return f"HTTP {code}"


def validate_row(
    row_idx: int,
    url: str,
    timeout: int,
    check_http: bool,
) -> tuple[int, str, str]:
    syntax_ok = is_valid_linkedin_syntax(url)
    syntax_label = "yes" if syntax_ok else "no"
    if not syntax_ok:
        return row_idx, syntax_label, "skipped (bad syntax)"
    if not check_http:
        return row_idx, syntax_label, "not checked"
    status = check_url_live(url, timeout)
    return row_idx, syntax_label, status


@dataclass
class LinkedInValidationStats:
    syntax_ok: int = 0
    syntax_bad: int = 0
    live_ok: int = 0
    other: int = 0


def run_validate_linkedin(
    wb: Workbook,
    *,
    sheet: Optional[str] = None,
    workers: int = 10,
    timeout: int = 15,
    syntax_only: bool = False,
    limit: int = 0,
    log: LogFn = print,
) -> tuple[Optional[Worksheet], LinkedInValidationStats]:
    """Validate LinkedIn Profile URLs in the workbook (in memory). Does not save."""
    ws, sheet_name = resolve_validation_worksheet(wb, sheet, log=log)
    if ws is None:
        return None, LinkedInValidationStats()

    log(f"Validate LinkedIn [{sheet_name}]")

    headers = get_header_row(ws)
    profile_col = find_profile_column(headers)
    if profile_col is None:
        profile_col, created_profile = ensure_column(ws, headers, PROFILE_HEADER)
        if created_profile:
            log(f"Added column: {PROFILE_HEADER}")

    valid_col, created_valid = ensure_column(ws, headers, URL_VALID_HEADER)
    if created_valid:
        log(f"Added column: {URL_VALID_HEADER}")

    status_col, created_status = ensure_column(ws, headers, URL_STATUS_HEADER)
    if created_status:
        log(f"Added column: {URL_STATUS_HEADER}")

    rows = collect_urls_for_validation(ws, profile_col)
    if limit > 0:
        rows = rows[:limit]

    if not rows:
        log("No LinkedIn URLs found to validate.")
        return ws, LinkedInValidationStats()

    log(
        f"URLs to validate: {len(rows)} | workers={workers} | "
        f"http={'off' if syntax_only else 'on'}"
    )

    syntax_results: dict[int, str] = {}
    status_results: dict[int, str] = {}
    stats = LinkedInValidationStats()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                validate_row,
                row_idx,
                url,
                timeout,
                not syntax_only,
            ): (row_idx, company, url)
            for row_idx, company, url in rows
        }
        done = 0
        for fut in as_completed(futures):
            row_idx, company, url = futures[fut]
            done += 1
            try:
                r_idx, syntax_label, status_label = fut.result()
            except Exception as exc:
                log(f"[{done}/{len(rows)}] {company}: error {exc}")
                stats.other += 1
                continue

            syntax_results[r_idx] = syntax_label
            status_results[r_idx] = status_label
            if syntax_label == "yes":
                stats.syntax_ok += 1
            else:
                stats.syntax_bad += 1
            if status_label == "OK" or status_label.startswith("OK ("):
                stats.live_ok += 1

            log(f"[{done}/{len(rows)}] {company}: syntax={syntax_label} status={status_label}")

    write_column_values(ws, valid_col, syntax_results)
    write_column_values(ws, status_col, status_results)

    log(
        f"LinkedIn validation done. syntax_ok={stats.syntax_ok} "
        f"syntax_bad={stats.syntax_bad} live_ok={stats.live_ok}"
    )
    return ws, stats
