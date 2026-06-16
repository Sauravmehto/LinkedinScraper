"""
Step 3 — JavaScript-rendered pages (free, slower).

When: Steps 1 and 2 did not find a LinkedIn URL.
What: Headless Chromium via Playwright; render homepage + same-site /about, /contact paths.
Requires: pipenv run playwright install chromium  (one-time per machine)

Threading: Playwright sync API must run on one thread. The CLI runs Step 3 in a
second sequential pass after Steps 1–2 (see scrape_linkedin_profiles.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from .http_client import USER_AGENT
from .linkedin_extract import extract_deep_from_page, same_registrable_host
from .result import ScrapeResult
from .step2_deep_links import _extra_urls

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

_pw: Optional["Playwright"] = None
_browser: Optional["Browser"] = None
_context: Optional["BrowserContext"] = None


def _playwright_missing_result() -> ScrapeResult:
    return ScrapeResult(
        profile_url=None,
        method="not_found",
        note="step3: playwright not installed — run: python -m pipenv run playwright install chromium",
    )


def _ensure_context() -> tuple[Optional["BrowserContext"], Optional[ScrapeResult]]:
    global _pw, _browser, _context
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, _playwright_missing_result()

    if _context is not None:
        return _context, None

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=True)
    _context = _browser.new_context(
        user_agent=USER_AGENT,
        locale="en-US",
    )
    return _context, None


def _close_context() -> None:
    global _pw, _browser, _context
    if _context is not None:
        _context.close()
        _context = None
    if _browser is not None:
        _browser.close()
        _browser = None
    if _pw is not None:
        _pw.stop()
        _pw = None


def _try_rendered_page(
    page: "Page",
    url: str,
    timeout_ms: int,
    *,
    label: str,
) -> ScrapeResult | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # Brief pause for late footer/social icons on SPAs
        page.wait_for_timeout(800)
        html = page.content()
    except Exception:
        return None

    profile = extract_deep_from_page(html, url)
    if profile:
        return ScrapeResult(
            profile_url=profile,
            method="step3",
            note=f"step3: {label}",
        )
    return None


def _run_locked(base_url: str, timeout: float) -> ScrapeResult:
    context, err = _ensure_context()
    if err is not None:
        return err
    assert context is not None

    timeout_ms = int(timeout * 1000)
    page = context.new_page()
    try:
        hit = _try_rendered_page(page, base_url, timeout_ms, label="homepage")
        if hit:
            return hit

        for extra_url in _extra_urls(base_url):
            if not same_registrable_host(extra_url, base_url):
                continue
            path = urlparse(extra_url).path or "/"
            hit = _try_rendered_page(page, extra_url, timeout_ms, label=path)
            if hit:
                return hit
    finally:
        page.close()

    return ScrapeResult(
        profile_url=None,
        method="not_found",
        note="step3: no linkedin after JS render",
    )


def run(base_url: str, timeout: float = 15.0) -> ScrapeResult:
    """Render company site in Chromium and extract LinkedIn links (main thread only)."""
    return _run_locked(base_url, timeout)


def shutdown_browser() -> None:
    """Release Playwright resources (call from the same thread that ran Step 3)."""
    try:
        _close_context()
    except Exception:
        pass
