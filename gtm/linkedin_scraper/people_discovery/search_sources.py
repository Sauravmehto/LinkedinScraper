"""Parallel search-source runners for people discovery."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import httpx

from gtm.linkedin_scraper.config import FallbackConfig
from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

from .candidate_extract import normalize_profile_url
from .types import RawProfileHit

LINKEDIN_IN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_%\-\.]+/?",
    re.IGNORECASE,
)


def _extract_hits_from_text(text: str, source: str) -> list[RawProfileHit]:
    urls = LINKEDIN_IN_RE.findall(text or "")
    out: list[RawProfileHit] = []
    for i, url in enumerate(urls[:8]):
        normalized = normalize_profile_url(url)
        if not normalized:
            continue
        out.append(
            RawProfileHit(
                url=normalized,
                source=source,
                title="",
                snippet="",
                confidence_hint=max(0.1, 0.8 - (i * 0.05)),
            )
        )
    return out


def _fetch_text(url: str, timeout: float = 15.0, headers: dict | None = None) -> str | None:
    try:
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=merged) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except (httpx.HTTPError, TimeoutError, OSError):
        return None


def _search_bing(query: str, timeout: float) -> list[RawProfileHit]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    html = _fetch_text(url, timeout=timeout)
    return _extract_hits_from_text(html or "", "bing")


def _search_ddg(query: str, timeout: float) -> list[RawProfileHit]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    html = _fetch_text(url, timeout=timeout)
    return _extract_hits_from_text(html or "", "ddg")


def _hits_from_serper_results(data: dict) -> list[RawProfileHit]:
    hits: list[RawProfileHit] = []
    seen: set[str] = set()
    for item in data.get("organic", []):
        if not isinstance(item, dict):
            continue
        url = normalize_profile_url(str(item.get("link") or ""))
        title = str(item.get("title") or "")[:200]
        snippet = str(item.get("snippet") or "")[:500]
        if not url or "/in/" not in url.lower():
            blob = " ".join(
                str(item.get(k) or "")
                for k in ("link", "title", "snippet")
            )
            for match in LINKEDIN_IN_RE.findall(blob):
                url = normalize_profile_url(match)
                if not url:
                    continue
                key = url.lower()
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    RawProfileHit(
                        url=url,
                        source="serper",
                        title=title,
                        snippet=snippet,
                        confidence_hint=0.85,
                    )
                )
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            RawProfileHit(
                url=url,
                source="serper",
                title=title,
                snippet=snippet,
                confidence_hint=0.88,
            )
        )
    return hits


def _search_serper(query: str, timeout: float, api_key: str) -> list[RawProfileHit]:
    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS) as client:
            resp = client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": 10, "gl": "us"},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        return []
    return _hits_from_serper_results(data)


def _hits_from_tavily_results(data: dict) -> list[RawProfileHit]:
    hits: list[RawProfileHit] = []
    seen: set[str] = set()
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        url = normalize_profile_url(str(item.get("url") or ""))
        if not url or "/in/" not in url.lower():
            # Also scan content for embedded profile URLs
            blob = " ".join(
                str(item.get(k) or "")
                for k in ("url", "title", "content", "raw_content")
            )
            for match in LINKEDIN_IN_RE.findall(blob):
                url = normalize_profile_url(match)
                if not url:
                    continue
                key = url.lower()
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    RawProfileHit(
                        url=url,
                        source="tavily",
                        title=str(item.get("title") or "")[:200],
                        snippet=str(item.get("content") or "")[:500],
                        confidence_hint=0.8,
                    )
                )
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            RawProfileHit(
                url=url,
                source="tavily",
                title=str(item.get("title") or "")[:200],
                snippet=str(item.get("content") or "")[:500],
                confidence_hint=0.82,
            )
        )
    return hits


def _search_tavily(query: str, timeout: float, api_key: str) -> list[RawProfileHit]:
    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 10,
                    "include_domains": ["linkedin.com"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        return []
    return _hits_from_tavily_results(data)


def run_search_sources(
    *,
    queries: list[str],
    enabled_sources: tuple[str, ...],
    cfg: FallbackConfig,
    timeout: float = 15.0,
    workers: int = 8,
) -> list[RawProfileHit]:
    tasks = []
    hits: list[RawProfileHit] = []
    enabled = {s.strip().lower() for s in enabled_sources if s.strip()}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for q in queries:
            if "bing" in enabled:
                tasks.append(pool.submit(_search_bing, q, timeout))
            if "ddg" in enabled:
                tasks.append(pool.submit(_search_ddg, q, timeout))
            if "serper" in enabled and cfg.serper_api_key:
                tasks.append(pool.submit(_search_serper, q, timeout, cfg.serper_api_key))
            if "tavily" in enabled and cfg.tavily_api_key:
                tasks.append(pool.submit(_search_tavily, q, timeout, cfg.tavily_api_key))

        for fut in as_completed(tasks):
            try:
                hits.extend(fut.result())
            except Exception:
                continue
    return hits


def run_free_search_staged(
    *,
    queries: list[str],
    cfg: FallbackConfig,
    timeout: float = 15.0,
    workers: int = 8,
    use_bing: bool = True,
    use_ddg: bool = True,
    skip_ddg_if_bing_quality_at_least: int = 2,
    company_name: str = "",
) -> list[RawProfileHit]:
    """Bing first; skip DDG when Bing already has enough quality profiles."""
    from .candidate_extract import dedupe_profile_hits
    from .quality import count_quality_profiles

    hits: list[RawProfileHit] = []

    if use_bing and queries:
        hits.extend(
            run_search_sources(
                queries=queries,
                enabled_sources=("bing",),
                cfg=cfg,
                timeout=timeout,
                workers=workers,
            )
        )

    if use_ddg and queries:
        bing_quality = count_quality_profiles(
            dedupe_profile_hits(hits),
            company_name=company_name,
        )
        if bing_quality < skip_ddg_if_bing_quality_at_least:
            hits.extend(
                run_search_sources(
                    queries=queries,
                    enabled_sources=("ddg",),
                    cfg=cfg,
                    timeout=timeout,
                    workers=workers,
                )
            )

    return hits


def run_serper_fallback(
    *,
    queries: list[str],
    cfg: FallbackConfig,
    timeout: float = 15.0,
    workers: int = 8,
) -> list[RawProfileHit]:
    """Run Serper queries when free Bing/DDG quality is below threshold."""
    if not queries or not cfg.serper_api_key:
        return []
    return run_search_sources(
        queries=queries,
        enabled_sources=("serper",),
        cfg=cfg,
        timeout=timeout,
        workers=workers,
    )
