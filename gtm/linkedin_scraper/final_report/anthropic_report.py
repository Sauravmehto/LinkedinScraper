"""LLM-powered cleanup and formatting for final report Excel output.

Uses the unified llm_fallback chain: Anthropic -> Gemini -> Groq -> Mistral -> Cloudflare.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from gtm.linkedin_scraper.llm_fallback import llm_call_from_config

from .hubspot_data_template import (
    build_hubspot_rows,
    build_source_payloads,
    normalize_row_dict,
)
from .template_map import (
    ReportDefaults,
    build_row_dicts,
    build_template_source_payloads,
    detect_template_format,
)

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


def _system_prompt(headers: list[str], template_format: str) -> str:
    header_list = ", ".join(headers)
    base = (
        "You format B2B contact rows for CRM import. "
        f'Output ONLY valid JSON: {{"rows": [ ... ]}} where each object uses EXACTLY '
        f"these keys (no extras): {header_list}. "
        "Clean First Name and Last Name (proper case, remove LinkedIn slug junk). "
        "Normalize Job Title to role only (no person name, company, or LinkedIn). "
        "Keep Email lowercase when present. "
        "Do not invent emails or phone numbers. "
        'Drop rows with keep=false (add keep boolean); default keep=true for valid executives.'
    )
    if template_format == "hubspot_data":
        return (
            base
            + " Fill City and State/Region from _company_headquarters when empty. "
            "Company Domain Name should be hostname only (no https). "
            "Industry from _asset_focus when Industry is empty."
        )
    return (
        base
        + " Preserve Score, Role target, Source, AUM, and Asset focus when present. "
        "Website URL should include https:// when a domain is known."
    )


def format_rows_with_llm(
    *,
    source_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    headers: list[str],
    template_format: str,
    cfg,
    timeout: float = 90.0,
    batch_size: int = 20,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Send merged rows to an LLM (fallback chain); return cleaned rows matching template headers.
    On failure uses pre-built deterministic fallback rows for that batch.
    """
    _log = log or (lambda _m: None)
    if not source_rows:
        return fallback_rows or [_strip_internal(r, headers) for r in source_rows]

    cleaned: list[dict[str, Any]] = []
    chunk_size = max(1, batch_size)
    system = _system_prompt(headers, template_format)

    for start in range(0, len(source_rows), chunk_size):
        end = start + chunk_size
        chunk = source_rows[start:end]
        chunk_fallback = fallback_rows[start:end]
        user_content = json.dumps(
            {"template_columns": headers, "contacts": chunk},
            ensure_ascii=False,
        )
        text = llm_call_from_config(
            cfg,
            system=system,
            user_content=user_content,
            max_tokens=8192,
            timeout=timeout,
            log=_log,
        )
        if not text:
            _log("LLM final report batch failed; using deterministic rows")
            cleaned.extend(chunk_fallback)
            continue

        parsed = _parse_json_array(text)
        if not parsed:
            _log("LLM final report: empty JSON; using deterministic rows for batch")
            cleaned.extend(chunk_fallback)
            continue

        for row in parsed:
            if row.get("keep") is False:
                continue
            cleaned.append(normalize_row_dict(row, headers))

    if not cleaned:
        _log("LLM final report: no rows returned; using deterministic mapping")
        return fallback_rows

    _log(f"LLM final report: {len(cleaned)} row(s) after cleanup")
    return cleaned


def format_rows_with_anthropic(
    *,
    source_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    headers: list[str],
    template_format: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 90.0,
    batch_size: int = 20,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Backwards-compatible wrapper — uses Anthropic-only path (no fallback chain)."""
    from gtm.linkedin_scraper.config import FallbackConfig

    cfg = FallbackConfig(
        brave_api_key=None,
        serper_api_key=None,
        tavily_api_key=None,
        apollo_api_key=None,
        anthropic_api_key=api_key,
        anthropic_model=model,
    )
    return format_rows_with_llm(
        source_rows=source_rows,
        fallback_rows=fallback_rows,
        headers=headers,
        template_format=template_format,
        cfg=cfg,
        timeout=timeout,
        batch_size=batch_size,
        log=log,
    )


def _strip_internal(row: dict[str, Any], headers: list[str]) -> dict[str, Any]:
    base = {k: v for k, v in row.items() if not str(k).startswith("_")}
    return normalize_row_dict(base, headers)


def _deterministic_rows(
    candidates: list,
    companies_by_name: dict,
    headers: list[str],
    template_format: str,
    defaults: ReportDefaults | None,
) -> list[dict[str, Any]]:
    if template_format == "gtm_final":
        return build_row_dicts(
            candidates,
            companies_by_name,
            headers,
            defaults=defaults,
        )
    rows = build_hubspot_rows(candidates, companies_by_name)
    return [normalize_row_dict(r, headers) for r in rows]


def _source_payloads(
    candidates: list,
    companies_by_name: dict,
    headers: list[str],
    template_format: str,
    defaults: ReportDefaults | None,
) -> list[dict[str, Any]]:
    if template_format == "gtm_final":
        return build_template_source_payloads(
            candidates,
            companies_by_name,
            headers,
            defaults=defaults,
        )
    return build_source_payloads(candidates, companies_by_name)


def build_final_rows(
    candidates,
    companies_by_name: dict,
    *,
    headers: list[str],
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    use_anthropic: bool = True,
    cfg=None,
    defaults: ReportDefaults | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Returns (row dicts, method label: llm|deterministic).

    Pass *cfg* (FallbackConfig) to enable the full LLM fallback chain.
    Passing only *api_key* still works for backwards compatibility.
    """
    from gtm.linkedin_scraper.config import FallbackConfig, available_llm_providers

    template_format = detect_template_format(headers)
    deterministic = _deterministic_rows(
        candidates,
        companies_by_name,
        headers,
        template_format,
        defaults,
    )

    if not use_anthropic:
        return deterministic, "deterministic"

    # Build effective config: prefer passed cfg; fall back to api_key-only stub
    if cfg is None and api_key:
        cfg = FallbackConfig(
            brave_api_key=None,
            serper_api_key=None,
            tavily_api_key=None,
            apollo_api_key=None,
            anthropic_api_key=api_key,
            anthropic_model=model,
        )

    if cfg is None:
        return deterministic, "deterministic"

    providers = available_llm_providers(cfg)
    if not providers:
        return deterministic, "deterministic"

    payloads = _source_payloads(
        candidates,
        companies_by_name,
        headers,
        template_format,
        defaults,
    )
    rows = format_rows_with_llm(
        source_rows=payloads,
        fallback_rows=deterministic,
        headers=headers,
        template_format=template_format,
        cfg=cfg,
        log=log,
    )
    return rows, "llm"
