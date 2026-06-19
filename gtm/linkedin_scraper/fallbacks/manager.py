"""Fallback waterfall manager (Steps 7-9 default; 4-6 optional via --fallback-steps)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from gtm.linkedin_scraper.config import FallbackConfig

from . import (
    step4_bing,
    step5_brave,
    step6_ddg,
    step7_team_pages,
    step8_tavily,
    step9_apollo,
)
from .linkedin_rules import pick_best_candidate
from .types import FallbackResult, LinkedInCandidate

LogFn = Callable[[str], None]

STEP_METHOD_MAP: dict[int, str] = {
    4: "step4_bing",
    5: "step5_brave",
    6: "step6_ddg",
    7: "step7_team",
    8: "step8_tavily",
    9: "step9_apollo",
}


@dataclass
class FallbackStats:
    checked: int = 0
    found: int = 0
    by_step: dict[int, int] = field(default_factory=lambda: {4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0})


def _run_step(
    step: int,
    *,
    company: str,
    website: str,
    timeout: float,
    cfg: FallbackConfig,
) -> list[LinkedInCandidate]:
    if step == 4:
        return step4_bing.search(company, website, timeout=timeout)
    if step == 5:
        return step5_brave.search(
            company,
            website,
            api_key=cfg.brave_api_key,
            timeout=timeout,
        )
    if step == 6:
        return step6_ddg.search(company, website, timeout=timeout)
    if step == 7:
        return step7_team_pages.search(website, timeout=timeout)
    if step == 8:
        return step8_tavily.search(
            company,
            website,
            api_key=cfg.tavily_api_key,
            timeout=timeout,
        )
    if step == 9:
        return step9_apollo.search(company, api_key=cfg.apollo_api_key, timeout=timeout)
    return []


def run_fallback_waterfall(
    *,
    company: str,
    website: str,
    enabled_steps: tuple[int, ...],
    timeout: float,
    cfg: FallbackConfig,
    stats: FallbackStats,
    log: LogFn = print,
) -> FallbackResult:
    stats.checked += 1
    for step in enabled_steps:
        if step not in STEP_METHOD_MAP:
            continue
        candidates = _run_step(
            step,
            company=company,
            website=website,
            timeout=timeout,
            cfg=cfg,
        )
        best = pick_best_candidate(candidates)
        if not best:
            continue
        stats.by_step[step] = stats.by_step.get(step, 0) + 1
        stats.found += 1
        method = STEP_METHOD_MAP[step]
        log(f"[{method}] {company}: {best.url}")
        return FallbackResult(
            profile_url=best.url,
            method=method,
            note=best.reason,
        )
    return FallbackResult(
        profile_url=None,
        method="not_found",
        note="fallbacks: no linkedin found",
    )
