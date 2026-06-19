"""Claude-powered cleanup and formatting for Hubspot Data.xlsx final report."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

from .hubspot_data_template import (
    build_hubspot_rows,
    build_source_payloads,
    normalize_row_dict,
)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def _parse_json_array(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return [x for x in data["rows"] if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    return []


def format_hubspot_rows_with_anthropic(
    *,
    source_rows: list[dict[str, Any]],
    headers: list[str],
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
    batch_size: int = 25,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Send merged rows to Claude; return cleaned rows matching template headers.
    Falls back to stripping underscore fields from source rows on API failure.
    """
    _log = log or (lambda _m: None)
    if not api_key or not source_rows:
        return [_strip_internal(r, headers) for r in source_rows]

    cleaned: list[dict[str, Any]] = []
    chunk_size = max(1, batch_size)
    header_list = ", ".join(headers)

    for start in range(0, len(source_rows), chunk_size):
        chunk = source_rows[start : start + chunk_size]
        system = (
            "You format B2B contact rows for HubSpot import. "
            f"Output ONLY valid JSON: {{\"rows\": [ ... ]}} where each object uses EXACTLY "
            f"these keys (no extras): {header_list}. "
            "Clean First Name and Last Name (proper case, remove LinkedIn slug junk). "
            "Normalize Job Title. Keep Email lowercase. "
            "Fill City and State/Region from _company_headquarters when empty. "
            "Company Domain Name should be hostname only (no https). "
            "Industry from _asset_focus when Industry is empty. "
            "Drop rows with keep=false (add keep boolean); default keep=true for valid executives. "
            "Do not invent emails or phone numbers."
        )
        user_content = json.dumps(
            {"template_columns": headers, "contacts": chunk},
            ensure_ascii=False,
        )
        body = {
            "model": model,
            "max_tokens": 8192,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers_http = {
            **DEFAULT_HEADERS,
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            with httpx.Client(timeout=timeout, headers=headers_http) as client:
                resp = client.post(ANTHROPIC_API_URL, json=body)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, TimeoutError, OSError, ValueError, KeyError) as exc:
            _log(f"Anthropic final report batch failed ({type(exc).__name__}); using deterministic rows")
            cleaned.extend(_strip_internal(r, headers) for r in chunk)
            continue

        text_parts = [
            b.get("text", "")
            for b in (data.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        parsed = _parse_json_array("\n".join(text_parts))
        if not parsed:
            _log("Anthropic final report: empty JSON; using deterministic rows for batch")
            cleaned.extend(_strip_internal(r, headers) for r in chunk)
            continue

        for row in parsed:
            if row.get("keep") is False:
                continue
            cleaned.append(normalize_row_dict(row, headers))

    if not cleaned:
        _log("Anthropic final report: no rows returned; using deterministic mapping")
        return [_strip_internal(r, headers) for r in source_rows]

    _log(f"Anthropic final report: {len(cleaned)} row(s) after cleanup")
    return cleaned


def _strip_internal(row: dict[str, Any], headers: list[str]) -> dict[str, Any]:
    base = {k: v for k, v in row.items() if not str(k).startswith("_")}
    return normalize_row_dict(base, headers)


def build_final_rows(
    candidates,
    companies_by_name: dict,
    *,
    headers: list[str],
    api_key: str | None,
    model: str,
    use_anthropic: bool,
    log: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Returns (row dicts, method label: anthropic|deterministic)."""
    if use_anthropic and api_key:
        payloads = build_source_payloads(candidates, companies_by_name)
        rows = format_hubspot_rows_with_anthropic(
            source_rows=payloads,
            headers=headers,
            api_key=api_key,
            model=model,
            log=log,
        )
        return rows, "anthropic"
    rows = build_hubspot_rows(candidates, companies_by_name)
    return [normalize_row_dict(r, headers) for r in rows], "deterministic"
