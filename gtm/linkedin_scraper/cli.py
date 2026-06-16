"""Command-line interface for the GTM LinkedIn scraper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from openpyxl import load_workbook

from gtm.linkedin_scraper.config import load_fallback_config
from gtm.linkedin_scraper.io_utils import (
    DEFAULT_SAMPLE_XLSX,
    OUTPUT_DIR,
    default_output_path,
    prepare_workbook,
    save_workbook,
)
from gtm.linkedin_scraper.people_discovery import DiscoverPeopleParams, run_people_discovery
from gtm.linkedin_scraper.people_discovery.contact_enrichment import (
    enrich_candidates,
    load_company_hq_phones,
    load_company_websites,
    read_people_workbook,
    write_people_workbook,
)
from gtm.linkedin_scraper.people_discovery.contact_enrichment.enrich_phones import (
    enrich_phones_in_workbook,
)
from gtm.linkedin_scraper.final_report import (
    DEFAULT_OUTPUT as FINAL_REPORT_DEFAULT_OUTPUT,
    DEFAULT_TEMPLATE as FINAL_REPORT_DEFAULT_TEMPLATE,
    build_final_report,
    resolve_template_path,
)
from gtm.linkedin_scraper.final_report.build import GTM_FINAL_REPORT_OUTPUT
from gtm.linkedin_scraper.people_discovery.candidate_cap import (
    DEFAULT_MAX_PER_COMPANY,
    cap_candidates_per_company,
)
from gtm.linkedin_scraper.hubspot_sync import sync_to_hubspot
from gtm.linkedin_scraper.hubspot_sync.client import validate_crm_api_token
from gtm.linkedin_scraper.people_discovery.pipeline import DEFAULT_MIN_SCORE
from gtm.linkedin_scraper.scrape import parse_steps, run_scrape
from gtm.linkedin_scraper.validators.linkedin_urls import run_validate_linkedin
from gtm.linkedin_scraper.validators.official_websites import run_validate_websites


def log(msg: str) -> None:
    print(msg, flush=True)


def resolve_output(input_path: Path, output_path: Optional[Path]) -> Path:
    if output_path is None:
        return default_output_path(input_path)
    return output_path


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        "--xlsx",
        type=Path,
        required=True,
        dest="input",
        help="Path to input Excel file (never overwritten)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to result Excel file (default: output/<input_stem>_enriched.xlsx)",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Worksheet name (default: auto-detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving the output file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N rows (0 = all)",
    )


def add_scrape_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workers",
        type=int,
        default=25,
        help="Concurrent threads for scrape (default: 25)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--steps",
        default="1,2",
        help="Pipeline steps: 1=httpx homepage, 2=deep links, 3=Playwright (default: 1,2)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even when Profile URL is already set",
    )
    parser.add_argument(
        "--enable-fallbacks",
        action="store_true",
        help="Enable fallback Steps 4-9 after Step 3 misses (default: off)",
    )
    parser.add_argument(
        "--fallback-steps",
        default="4,5,6,7,8,9",
        help="Fallback steps order (default: 4,5,6,7,8,9)",
    )


def add_validation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Concurrent threads (default: 10 for LinkedIn, 15 for websites in run-all)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15)",
    )


def add_people_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--enable-people-discovery",
        action="store_true",
        help="Enable decision-maker people discovery flow",
    )
    parser.add_argument(
        "--max-candidates-per-role",
        type=int,
        default=1,
        help="Internal per-role gather limit before company cap (default: 1)",
    )
    parser.add_argument(
        "--max-people-per-company",
        type=int,
        default=DEFAULT_MAX_PER_COMPANY,
        help=f"Maximum decision makers to keep per company by score (default: {DEFAULT_MAX_PER_COMPANY})",
    )
    parser.add_argument(
        "--apollo-sufficient-hits",
        type=int,
        default=3,
        help="Skip Apollo when free + Serper found this many quality profiles (default: 3)",
    )
    parser.add_argument(
        "--min-people-before-tavily",
        type=int,
        default=2,
        help="Only call Tavily if quality profiles are below this (default: 2)",
    )
    parser.add_argument(
        "--tavily-fallback-queries",
        type=int,
        default=4,
        help="Max Tavily queries per company when used as fallback (default: 4)",
    )
    parser.add_argument(
        "--serper-fallback-queries",
        type=int,
        default=3,
        help="Max Serper queries per company when quality is below Apollo threshold (default: 3)",
    )
    parser.add_argument(
        "--company-type-column",
        default="Company Type",
        help="Optional worksheet column containing company type override",
    )
    parser.add_argument(
        "--people-output",
        type=Path,
        default=None,
        help="Decision-maker output file (default: output/decision_makers.xlsx)",
    )
    parser.add_argument(
        "--enable-enrichment",
        action="store_true",
        help="Enable Anthropic enrichment (default: on when ANTHROPIC_API_KEY is set)",
    )
    parser.add_argument(
        "--no-anthropic",
        action="store_true",
        help="Disable Anthropic enrichment even if API key is configured",
    )
    parser.add_argument(
        "--enrichment-threshold",
        default="HIGH",
        choices=("HIGH", "MEDIUM"),
        help="Reserved threshold for enrichment gating",
    )
    parser.add_argument(
        "--people-sources",
        default="auto",
        help="People sources: auto (bing,ddg + serper/apollo from .env), or comma list (bing,ddg,serper,apollo,tavily). Brave is not used for people.",
    )
    parser.add_argument(
        "--max-queries-per-company",
        type=int,
        default=8,
        help="Max free-tier search queries per company (default: 8)",
    )
    parser.add_argument(
        "--skip-ddg-if-bing-quality",
        type=int,
        default=2,
        help="Skip DDG when Bing already has this many quality profiles (default: 2)",
    )
    parser.add_argument(
        "--use-people-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use disk cache for people discovery (default: on)",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore cache and re-fetch people for all companies",
    )
    parser.add_argument(
        "--coverage-mode",
        choices=("standard", "max"),
        default="standard",
        help="standard=5 people/company cap; max=unlimited contacts, Playwright, expanded roles",
    )
    parser.add_argument(
        "--enable-playwright-people",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use Playwright for JS-heavy team/leadership pages (default: on in max coverage)",
    )
    parser.add_argument(
        "--min-people-before-serper",
        type=int,
        default=None,
        help="Skip Serper when profile count is at or above this (default: 3, max mode: 12)",
    )
    parser.add_argument(
        "--min-people-before-apollo",
        type=int,
        default=None,
        help="Skip Apollo when scored profile count is at or above this (default: 5)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        help=f"Minimum score to export; also used for paid-API skip gates (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--enable-contact-enrichment",
        action="store_true",
        help="After people discovery, enrich work email and phones via Apollo people/match",
    )
    parser.add_argument(
        "--apollo-contact-delay",
        type=float,
        default=0.5,
        help="Seconds between Apollo people/match calls during contact enrichment (default: 0.5)",
    )
    parser.add_argument(
        "--enrich-all-contacts",
        action="store_true",
        help="Re-call Apollo for contacts even when email or phone is already set",
    )


def add_enrich_contacts_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Decision-makers Excel (e.g. output/decision_makers.xlsx)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: overwrite --input)",
    )
    parser.add_argument(
        "--companies-input",
        type=Path,
        default=None,
        help="Company workbook with Official Website column (e.g. output/result_final.xlsx)",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Worksheet name for decision-makers file (default: auto)",
    )
    parser.add_argument(
        "--companies-sheet",
        default=None,
        help="Worksheet name for companies file (default: auto)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--apollo-contact-delay",
        type=float,
        default=0.5,
        help="Seconds between Apollo people/match calls (default: 0.5)",
    )
    parser.add_argument(
        "--enrich-all-contacts",
        action="store_true",
        help="Re-call Apollo even when email or phone is already present",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving the output file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only enrich first N people rows (0 = all)",
    )


def parse_fallback_steps(value: str) -> tuple[int, ...]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return (4, 5, 6, 7, 8, 9)
    return tuple(int(p) for p in parts)


def parse_people_sources(value: str) -> tuple[str, ...]:
    parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    if not parts:
        return ("bing", "ddg")
    return tuple(parts)


def resolve_people_sources_arg(value: str) -> tuple[str, ...] | None:
    """Return None for 'auto' so pipeline picks sources from configured API keys."""
    if (value or "").strip().lower() in ("", "auto"):
        return None
    return parse_people_sources(value)


def discover_people_params_from_args(args: argparse.Namespace) -> DiscoverPeopleParams:
    cfg = load_fallback_config()
    coverage_mode = getattr(args, "coverage_mode", "standard") or "standard"
    max_mode = coverage_mode == "max"
    min_score = getattr(args, "min_score", DEFAULT_MIN_SCORE) or DEFAULT_MIN_SCORE
    enable_contacts = bool(getattr(args, "enable_contact_enrichment", False))
    apollo_delay = float(getattr(args, "apollo_contact_delay", 0.5) or 0.5)
    enrich_all_contacts = bool(getattr(args, "enrich_all_contacts", False))

    enable_anthropic = not getattr(args, "no_anthropic", False) and (
        getattr(args, "enable_enrichment", False) or bool(cfg.anthropic_api_key)
    )

    if max_mode:
        pw_default = True
        return DiscoverPeopleParams(
            sheet=args.sheet,
            company_type_column=args.company_type_column,
            max_candidates_per_role=0,
            max_people_per_company=0,
            apollo_sufficient_hits=5,
            min_people_before_serper=args.min_people_before_serper
            if args.min_people_before_serper is not None
            else 5,
            min_people_before_apollo=args.min_people_before_apollo
            if args.min_people_before_apollo is not None
            else 5,
            min_people_before_tavily=3,
            tavily_fallback_max_queries=8,
            serper_fallback_max_queries=8,
            max_queries_per_company=24,
            skip_ddg_if_bing_quality=9999,
            people_sources=("bing", "serper", "apollo"),
            timeout=args.timeout,
            workers=args.workers,
            limit=args.limit,
            enable_anthropic=enable_anthropic,
            anthropic_enrich_only=True,
            use_people_cache=args.use_people_cache,
            refresh_cache=args.refresh_cache,
            coverage_mode="max",
            enable_playwright_people=(
                args.enable_playwright_people
                if args.enable_playwright_people is not None
                else pw_default
            ),
            min_candidate_score=min_score,
            force_tavily_fallback=True,
            enable_contact_enrichment=enable_contacts,
            apollo_contact_delay=apollo_delay,
            enrich_all_contacts=enrich_all_contacts,
        )

    min_serper = (
        args.min_people_before_serper
        if args.min_people_before_serper is not None
        else 5
    )
    min_apollo = (
        args.min_people_before_apollo
        if args.min_people_before_apollo is not None
        else 5
    )
    return DiscoverPeopleParams(
        sheet=args.sheet,
        company_type_column=args.company_type_column,
        max_candidates_per_role=args.max_candidates_per_role,
        max_people_per_company=args.max_people_per_company,
        apollo_sufficient_hits=5,
        min_people_before_serper=min_serper,
        min_people_before_apollo=min_apollo,
        min_people_before_tavily=3,
        tavily_fallback_max_queries=args.tavily_fallback_queries,
        serper_fallback_max_queries=args.serper_fallback_queries,
        max_queries_per_company=args.max_queries_per_company,
        skip_ddg_if_bing_quality=args.skip_ddg_if_bing_quality,
        people_sources=resolve_people_sources_arg(args.people_sources),
        timeout=args.timeout,
        workers=args.workers,
        limit=args.limit,
        enable_anthropic=enable_anthropic,
        use_people_cache=args.use_people_cache,
        refresh_cache=args.refresh_cache,
        coverage_mode="standard",
        enable_playwright_people=bool(args.enable_playwright_people),
        min_candidate_score=min_score,
        enable_contact_enrichment=enable_contacts,
        apollo_contact_delay=apollo_delay,
        enrich_all_contacts=enrich_all_contacts,
    )


def resolve_people_output(path: Optional[Path]) -> Path:
    return path or (OUTPUT_DIR / "decision_makers.xlsx")


def write_people_candidates(path: Path, candidates) -> None:
    write_people_workbook(path, candidates)


def cmd_scrape(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = resolve_output(input_path, args.output)

    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = prepare_workbook(input_path, output_path, dry_run=args.dry_run)
    steps = parse_steps(args.steps)

    ws, stats = run_scrape(
        wb,
        sheet=args.sheet,
        steps=steps,
        workers=args.workers,
        timeout=args.timeout,
        force=args.force,
        enable_fallbacks=args.enable_fallbacks,
        fallback_steps=parse_fallback_steps(args.fallback_steps),
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    save_workbook(wb, output_path, dry_run=args.dry_run)
    if not args.dry_run:
        log(f"Saved {output_path}")
    else:
        log("Dry run - workbook not saved")
    return 0


def cmd_validate_linkedin(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = resolve_output(input_path, args.output)

    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = prepare_workbook(input_path, output_path, dry_run=args.dry_run)
    ws, _stats = run_validate_linkedin(
        wb,
        sheet=args.sheet,
        workers=args.workers,
        timeout=args.timeout,
        syntax_only=args.syntax_only,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    save_workbook(wb, output_path, dry_run=args.dry_run)
    if not args.dry_run:
        log(f"Saved {output_path}")
    else:
        log("Dry run - workbook not saved")
    return 0


def cmd_validate_websites(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = resolve_output(input_path, args.output)

    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = prepare_workbook(input_path, output_path, dry_run=args.dry_run)
    ws, _stats = run_validate_websites(
        wb,
        sheet=args.sheet,
        workers=args.workers,
        timeout=args.timeout,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    save_workbook(wb, output_path, dry_run=args.dry_run)
    if not args.dry_run:
        log(f"Saved {output_path}")
    else:
        log("Dry run - workbook not saved")
    return 0


def cmd_discover_people(args: argparse.Namespace) -> int:
    input_path = args.input
    people_output = resolve_people_output(args.people_output)
    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log(f"Input:  {input_path}")
    log(f"People output: {people_output}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = load_workbook(input_path)
    params = discover_people_params_from_args(args)
    candidates, stats = run_people_discovery(wb, params=params, log=log)
    log(
        f"People discovery done. companies={stats.companies_checked} "
        f"with_candidates={stats.companies_with_candidates} candidates={stats.candidates_total} "
        f"cache_hits={stats.cache_hits}"
    )
    if not args.dry_run:
        try:
            write_people_candidates(people_output, candidates)
            log(f"Saved {people_output}")
        except PermissionError as exc:
            log(str(exc))
    else:
        log("Dry run - people output not saved")
    return 0


def cmd_enrich_contacts(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = args.output or input_path
    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))

    candidates = read_people_workbook(input_path, sheet=args.sheet)
    if args.limit > 0:
        candidates = candidates[: args.limit]
    if not candidates:
        log("No decision-maker rows found.")
        return 1

    websites: dict[str, str] = {}
    company_hq: dict[str, str] = {}
    companies_path = getattr(args, "companies_input", None)
    if companies_path and companies_path.exists():
        websites = load_company_websites(
            companies_path,
            sheet=getattr(args, "companies_sheet", None),
        )
        company_hq = load_company_hq_phones(
            companies_path,
            sheet=getattr(args, "companies_sheet", None),
        )
        log(f"Loaded {len(websites)} company website(s) from {companies_path}")
        if company_hq:
            log(f"Loaded {len(company_hq)} company HQ phone(s) from {companies_path}")
    elif companies_path:
        log(f"Companies file not found: {companies_path} (skipping website join)")

    cfg = load_fallback_config()
    enriched, stats = enrich_candidates(
        candidates,
        api_key=cfg.apollo_api_key,
        timeout=float(args.timeout),
        only_missing=not args.enrich_all_contacts,
        apollo_delay=float(args.apollo_contact_delay),
        websites_by_company=websites,
        company_hq_by_name=company_hq,
        log=log,
    )

    if not args.dry_run:
        try:
            write_people_workbook(output_path, enriched)
            log(f"Saved {output_path}")
        except PermissionError as exc:
            log(str(exc))
    else:
        log("Dry run - output not saved")
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = resolve_output(input_path, args.output)

    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log("=== GTM LinkedIn scraper: run-all ===")
    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = prepare_workbook(input_path, output_path, dry_run=args.dry_run)
    steps = parse_steps(args.steps)

    log("")
    log("--- Step 1/3: Scrape LinkedIn URLs ---")
    ws, _scrape_stats = run_scrape(
        wb,
        sheet=args.sheet,
        steps=steps,
        workers=args.workers,
        timeout=args.timeout,
        force=args.force,
        enable_fallbacks=args.enable_fallbacks,
        fallback_steps=parse_fallback_steps(args.fallback_steps),
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    log("")
    log("--- Step 2/3: Validate LinkedIn URLs ---")
    ws, _li_stats = run_validate_linkedin(
        wb,
        sheet=args.sheet,
        workers=args.workers,
        timeout=args.timeout,
        syntax_only=False,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    log("")
    log("--- Step 3/3: Validate Official Websites ---")
    ws, _web_stats = run_validate_websites(
        wb,
        sheet=args.sheet,
        workers=max(args.workers, 15),
        timeout=args.timeout,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    save_workbook(wb, output_path, dry_run=args.dry_run)
    log("")
    if not args.dry_run:
        log(f"Saved {output_path}")
    else:
        log("Dry run - workbook not saved")
    log("=== run-all complete ===")
    return 0


def cmd_run_full_intel(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = resolve_output(input_path, args.output)
    people_output = resolve_people_output(args.people_output)

    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    log("=== GTM full-intel ===")
    log(f"Input:  {input_path}")
    log(f"Company output: {output_path}" + (" (dry-run, not saved)" if args.dry_run else ""))
    if args.enable_people_discovery:
        log(f"People output: {people_output}" + (" (dry-run, not saved)" if args.dry_run else ""))

    wb = prepare_workbook(input_path, output_path, dry_run=args.dry_run)
    steps = parse_steps(args.steps)

    ws, _scrape_stats = run_scrape(
        wb,
        sheet=args.sheet,
        steps=steps,
        workers=args.workers,
        timeout=args.timeout,
        force=args.force,
        enable_fallbacks=args.enable_fallbacks,
        fallback_steps=parse_fallback_steps(args.fallback_steps),
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    ws, _li_stats = run_validate_linkedin(
        wb,
        sheet=args.sheet,
        workers=args.workers,
        timeout=args.timeout,
        syntax_only=False,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    ws, _web_stats = run_validate_websites(
        wb,
        sheet=args.sheet,
        workers=max(args.workers, 15),
        timeout=args.timeout,
        limit=args.limit,
        log=log,
    )
    if ws is None:
        return 1

    if args.enable_people_discovery:
        params = discover_people_params_from_args(args)
        candidates, stats = run_people_discovery(wb, params=params, log=log)
        max_per_co = int(getattr(args, "max_people_per_company", DEFAULT_MAX_PER_COMPANY) or 0)
        if max_per_co > 0:
            before = len(candidates)
            candidates = cap_candidates_per_company(candidates, max_per_company=max_per_co)
            log(f"Capped to {max_per_co}/company by score: {before} -> {len(candidates)} candidate(s)")
        log(
            f"People discovery done. companies={stats.companies_checked} "
            f"with_candidates={stats.companies_with_candidates} candidates={stats.candidates_total} "
            f"cache_hits={stats.cache_hits}"
        )
        if not args.dry_run:
            try:
                write_people_candidates(people_output, candidates)
                log(f"Saved {people_output}")
            except PermissionError as exc:
                log(str(exc))
        else:
            log("Dry run - people output not saved")

    save_workbook(wb, output_path, dry_run=args.dry_run)
    if not args.dry_run:
        log(f"Saved {output_path}")
    else:
        log("Dry run - workbook not saved")

    if (
        getattr(args, "build_final_report", True)
        and args.enable_people_discovery
        and not args.dry_run
        and people_output.exists()
    ):
        template_path = resolve_template_path(getattr(args, "final_report_template", None))
        if not template_path.exists():
            log(f"Skipping final report: template not found ({template_path})")
        else:
            final_out = (
                getattr(args, "final_report_output", None) or GTM_FINAL_REPORT_OUTPUT
            )
            lead_status, lifecycle_stage, owner_id = _hubspot_report_defaults(args)
            max_per_co = int(
                getattr(args, "max_people_per_company", DEFAULT_MAX_PER_COMPANY) or 0
            )
            log("--- Building GTM final report ---")
            try:
                build_final_report(
                    template_path=template_path,
                    companies_path=output_path if output_path.exists() else None,
                    people_path=people_output,
                    output_path=final_out,
                    min_score=getattr(args, "final_report_min_score", DEFAULT_MIN_SCORE),
                    require_email=getattr(args, "final_report_require_email", True),
                    require_phone=getattr(args, "final_report_require_phone", False),
                    lead_status=lead_status,
                    lifecycle_stage=lifecycle_stage,
                    owner_id=owner_id,
                    max_per_company=max_per_co,
                    dry_run=False,
                    log=log,
                )
            except PermissionError as exc:
                log(str(exc))
                return 1

    log("=== full-intel complete ===")
    return 0


def add_sync_hubspot_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--people",
        type=Path,
        default=OUTPUT_DIR / "decision_makers_new.xlsx",
        help="Decision-makers Excel (default: output/decision_makers_new.xlsx)",
    )
    parser.add_argument(
        "--companies",
        type=Path,
        default=OUTPUT_DIR / "result_final.xlsx",
        help="Company Excel with Official Website (default: output/result_final.xlsx)",
    )
    parser.add_argument(
        "--people-sheet",
        default=None,
        help="Sheet name in people workbook",
    )
    parser.add_argument(
        "--companies-sheet",
        default=None,
        help="Sheet name in companies workbook",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HubSpot API timeout seconds (default: 30)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.15,
        help="Delay between HubSpot API calls (default: 0.15)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without calling HubSpot",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only sync first N contacts (0 = all)",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="Do not create timeline notes with score/source/LinkedIn URLs",
    )


def cmd_sync_hubspot(args: argparse.Namespace) -> int:
    people_path = args.people
    companies_path = args.companies

    if not people_path.exists():
        log(f"People file not found: {people_path}")
        return 1

    cfg = load_fallback_config()
    token = cfg.hubspot_access_token
    if not token:
        log("Missing HUBSPOT_ACCESS_TOKEN in .env (Private App access token)")
        return 1
    token_err = validate_crm_api_token(token)
    if token_err:
        log(token_err)
        return 1

    log("=== HubSpot sync ===")
    log(f"People:    {people_path}")
    log(f"Companies: {companies_path}" + (" (missing, skip)" if not companies_path.exists() else ""))
    if args.dry_run:
        log("Mode: dry-run (no API writes)")

    stats = sync_to_hubspot(
        people_path=people_path,
        companies_path=companies_path if companies_path.exists() else None,
        access_token=token,
        dry_run=args.dry_run,
        limit=args.limit,
        lifecycle_stage=cfg.hubspot_lifecycle_stage or "lead",
        lead_status=cfg.hubspot_lead_status or "",
        owner_id=cfg.hubspot_contact_owner_id or "",
        person_linkedin_property=cfg.hubspot_person_linkedin_property or "",
        company_linkedin_property=cfg.hubspot_company_linkedin_property or "",
        skip_notes=args.skip_notes,
        request_delay=float(args.request_delay),
        timeout=float(args.timeout),
        log=log,
    )

    if stats.errors:
        log(f"Completed with {len(stats.errors)} error(s) — see messages above")
        return 1 if stats.contacts_skipped_error and not stats.contacts_created else 0
    log("=== HubSpot sync complete ===")
    return 0


def add_build_final_report_args(parser: argparse.ArgumentParser) -> None:
    from gtm.linkedin_scraper.final_report.build import GTM_FINAL_REPORT_OUTPUT, GTM_FINAL_TEMPLATE

    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help=f"Report template (default: {GTM_FINAL_TEMPLATE})",
    )
    parser.add_argument(
        "--companies",
        type=Path,
        default=OUTPUT_DIR / "result_final.xlsx",
        help="Company workbook (default: output/result_final.xlsx)",
    )
    parser.add_argument(
        "--people",
        type=Path,
        default=OUTPUT_DIR / "decision_makers_new.xlsx",
        help="Decision-makers workbook (default: output/decision_makers_new.xlsx)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Final report path (default: {GTM_FINAL_REPORT_OUTPUT})",
    )
    parser.add_argument(
        "--people-sheet",
        default=None,
        help="Sheet name in people workbook",
    )
    parser.add_argument(
        "--companies-sheet",
        default=None,
        help="Sheet name in companies workbook",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        help=f"Minimum decision-maker score (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--max-per-company",
        type=int,
        default=DEFAULT_MAX_PER_COMPANY,
        help=f"Max employees per company in report (default: {DEFAULT_MAX_PER_COMPANY})",
    )
    parser.add_argument(
        "--require-email",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only include rows with work_email (default: true)",
    )
    parser.add_argument(
        "--require-phone",
        action="store_true",
        help="Only include rows with direct_dial or hq_phone",
    )
    parser.add_argument(
        "--lead-status",
        default=None,
        help="Lead Status column (default: HUBSPOT_LEAD_STATUS from .env)",
    )
    parser.add_argument(
        "--lifecycle-stage",
        default=None,
        help="Lifecycle Stage column (default: HUBSPOT_LIFECYCLE_STAGE from .env)",
    )
    parser.add_argument(
        "--owner-id",
        default=None,
        help="Contact owner ID (default: HUBSPOT_CONTACT_OWNER_ID from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats without writing final_report.xlsx",
    )


def _hubspot_report_defaults(args: argparse.Namespace):
    cfg = load_fallback_config()
    lead = getattr(args, "lead_status", None)
    lifecycle = getattr(args, "lifecycle_stage", None)
    owner = getattr(args, "owner_id", None)
    return (
        lead if lead is not None else (cfg.hubspot_lead_status or ""),
        lifecycle if lifecycle is not None else (cfg.hubspot_lifecycle_stage or "lead"),
        owner if owner is not None else (cfg.hubspot_contact_owner_id or ""),
    )


def cmd_build_final_report(args: argparse.Namespace) -> int:
    people_path = args.people
    companies_path = args.companies
    template_path = resolve_template_path(args.template)
    output_path = args.output or GTM_FINAL_REPORT_OUTPUT

    if not people_path.exists():
        log(f"People file not found: {people_path}")
        return 1
    if not template_path.exists():
        log(f"Template not found: {template_path}")
        log("Place Hubspot CD 20052026 1.xlsx in output/ or data/")
        return 1

    lead_status, lifecycle_stage, owner_id = _hubspot_report_defaults(args)

    log("=== build-final-report ===")
    log(f"Template:  {template_path}")
    log(f"People:    {people_path}")
    log(f"Companies: {companies_path}" + (" (missing, skip join)" if not companies_path.exists() else ""))
    log(f"Output:    {output_path}" + (" (dry-run)" if args.dry_run else ""))

    try:
        build_final_report(
            template_path=template_path,
            companies_path=companies_path if companies_path.exists() else None,
            people_path=people_path,
            output_path=output_path,
            min_score=args.min_score,
            require_email=args.require_email,
            require_phone=args.require_phone,
            people_sheet=args.people_sheet,
            companies_sheet=args.companies_sheet,
            lead_status=lead_status,
            lifecycle_stage=lifecycle_stage,
            owner_id=owner_id,
            max_per_company=int(
                getattr(args, "max_per_company", DEFAULT_MAX_PER_COMPANY) or DEFAULT_MAX_PER_COMPANY
            ),
            dry_run=args.dry_run,
            log=log,
        )
    except PermissionError as exc:
        log(str(exc))
        return 1

    log("=== build-final-report complete ===")
    return 0


def add_enrich_phones_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        type=Path,
        default=OUTPUT_DIR / "decision_makers_new.xlsx",
        help="Decision-makers Excel (default: output/decision_makers_new.xlsx)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: overwrite --input)",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Worksheet name",
    )
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="Apollo webhook_url (default: APOLLO_WEBHOOK_URL from .env)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=None,
        help="Seconds to poll for each phone reveal (default: 120)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Seconds between poll requests (default: 5)",
    )
    parser.add_argument(
        "--submit-delay",
        type=float,
        default=0.5,
        help="Delay after each Apollo submit (default: 0.5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout per Apollo request (default: 30)",
    )
    parser.add_argument(
        "--only-missing-phones",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip rows that already have direct_dial (default: on)",
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Submit only without polling (not recommended)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List rows that would be enriched without calling Apollo",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N eligible rows (0 = all)",
    )


def cmd_enrich_phones(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = args.output or input_path
    if not input_path.exists():
        log(f"File not found: {input_path}")
        return 1

    cfg = load_fallback_config()
    if not cfg.apollo_api_key:
        log("Missing APOLLO_API_KEY in .env")
        return 1

    webhook_url = args.webhook_url or cfg.apollo_webhook_url or ""
    poll_timeout = (
        args.poll_timeout if args.poll_timeout is not None else cfg.apollo_phone_poll_timeout
    )
    poll_interval = (
        args.poll_interval if args.poll_interval is not None else cfg.apollo_phone_poll_interval
    )

    log("=== Apollo phone enrichment ===")
    log(f"Input:  {input_path}")
    log(f"Output: {output_path}" + (" (dry-run)" if args.dry_run else ""))
    if webhook_url:
        log(f"Webhook: {webhook_url[:48]}...")
    else:
        log("Webhook: not set (required unless --dry-run)")

    _final, stats = enrich_phones_in_workbook(
        input_path,
        output_path,
        api_key=cfg.apollo_api_key,
        webhook_url=webhook_url,
        sheet=args.sheet,
        only_missing=args.only_missing_phones,
        poll=not args.no_poll,
        poll_timeout=poll_timeout,
        poll_interval=poll_interval,
        submit_delay=float(args.submit_delay),
        request_timeout=float(args.timeout),
        limit=args.limit,
        dry_run=args.dry_run,
        log=log,
    )

    if not args.dry_run:
        log(f"Saved {output_path}")
    log("=== enrich-phones complete ===")
    return 0 if stats.errors == 0 else 1


def add_full_intel_report_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--build-final-report",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After run, merge into data/GTM_Final_report.xlsx (default: on)",
    )
    parser.add_argument(
        "--final-report-template",
        type=Path,
        default=None,
        help="Report template (default: data/GTM_Final_File.xlsx)",
    )
    parser.add_argument(
        "--final-report-output",
        type=Path,
        default=None,
        help="Final report path (default: data/GTM_Final_report.xlsx)",
    )
    parser.add_argument(
        "--final-report-min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        help=f"Min score for final report rows (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--final-report-require-email",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Final report: require work_email (default: true)",
    )
    parser.add_argument(
        "--final-report-require-phone",
        action="store_true",
        help="Final report: require direct_dial or hq_phone",
    )


def _register_full_intel_parser(
    sub: argparse._SubParsersAction,
    *,
    name: str,
    help_text: str,
    input_default: Path | None = None,
    command_defaults: dict | None = None,
) -> None:
    parser = sub.add_parser(name, help=help_text)
    if input_default is not None:
        parser.add_argument(
            "--input",
            "--xlsx",
            type=Path,
            default=input_default,
            dest="input",
            help=f"Company input Excel (default: {input_default})",
        )
        parser.add_argument(
            "--output",
            type=Path,
            default=OUTPUT_DIR / "result_final.xlsx",
            help="Company output (default: output/result_final.xlsx)",
        )
        parser.add_argument("--sheet", default=None, help="Worksheet name (default: auto)")
        parser.add_argument("--dry-run", action="store_true", help="Run without saving files")
        parser.add_argument("--limit", type=int, default=0, help="Only first N rows (0=all)")
    else:
        add_common_args(parser)
    add_scrape_args(parser)
    add_people_args(parser)
    add_full_intel_report_args(parser)
    defaults = {"func": cmd_run_full_intel, **(command_defaults or {})}
    parser.set_defaults(**defaults)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GTM LinkedIn scraper — scrape and validate company URLs from Excel.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="Scrape LinkedIn URLs from Official Website")
    add_common_args(p_scrape)
    add_scrape_args(p_scrape)
    p_scrape.set_defaults(func=cmd_scrape)

    p_li = sub.add_parser("validate-linkedin", help="Validate Profile URL syntax and HTTP status")
    add_common_args(p_li)
    add_validation_args(p_li)
    p_li.add_argument(
        "--syntax-only",
        action="store_true",
        help="Only check regex syntax; skip HTTP requests",
    )
    p_li.set_defaults(func=cmd_validate_linkedin)

    p_web = sub.add_parser("validate-websites", help="Validate Official Website HTTP status")
    add_common_args(p_web)
    add_validation_args(p_web)
    p_web.set_defaults(func=cmd_validate_websites)

    p_all = sub.add_parser(
        "run-all",
        help="Scrape + validate LinkedIn + validate websites (one output file)",
    )
    add_common_args(p_all)
    add_scrape_args(p_all)
    p_all.set_defaults(func=cmd_run_all)

    p_people = sub.add_parser(
        "discover-people",
        help="Discover decision-maker LinkedIn profiles (linkedin.com/in)",
    )
    add_common_args(p_people)
    add_validation_args(p_people)
    add_people_args(p_people)
    p_people.set_defaults(func=cmd_discover_people)

    p_contacts = sub.add_parser(
        "enrich-contacts",
        help="Enrich decision-makers with work email and phones (Apollo people/match)",
    )
    add_enrich_contacts_args(p_contacts)
    p_contacts.set_defaults(func=cmd_enrich_contacts)

    _register_full_intel_parser(
        sub,
        name="run-full-intel",
        help_text="Run company pipeline plus optional people discovery",
    )
    _register_full_intel_parser(
        sub,
        name="run-gtm",
        help_text="One command: companies + top 15 employees + GTM_Final_report.xlsx",
        input_default=DEFAULT_SAMPLE_XLSX,
        command_defaults={
            "enable_people_discovery": True,
            "enable_contact_enrichment": True,
            "coverage_mode": "max",
            "people_output": OUTPUT_DIR / "decision_makers.xlsx",
            "force": True,
            "enable_fallbacks": True,
            "steps": "1,2,3",
        },
    )

    p_hubspot = sub.add_parser(
        "sync-hubspot",
        help="Upsert companies and contacts from Excel into HubSpot CRM",
    )
    add_sync_hubspot_args(p_hubspot)
    p_hubspot.set_defaults(func=cmd_sync_hubspot)

    p_phones = sub.add_parser(
        "enrich-phones",
        help="Apollo async phone reveal (people/match + poll) into decision-makers Excel",
    )
    add_enrich_phones_args(p_phones)
    p_phones.set_defaults(func=cmd_enrich_phones)

    p_report = sub.add_parser(
        "build-final-report",
        help="Merge result_final + decision_makers into HubSpot CD template Excel",
    )
    add_build_final_report_args(p_report)
    p_report.set_defaults(func=cmd_build_final_report)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
