"""Playwright fallback for JS-rendered team/leadership pages."""

from __future__ import annotations


def fetch_page_via_playwright(url: str, *, timeout: float = 30.0) -> str | None:
    """Render a page in headless Chromium and return HTML, or None on failure."""
    if not url:
        return None
    try:
        from gtm.linkedin_scraper.scrapers import step3_playwright

        context, err = step3_playwright._ensure_context()
        if err is not None or context is None:
            return None

        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            page.wait_for_timeout(800)
            html = page.content()
            return html if html and len(html.strip()) >= 200 else None
        finally:
            page.close()
    except Exception:
        return None


def shutdown_playwright() -> None:
    try:
        from gtm.linkedin_scraper.scrapers import step3_playwright

        step3_playwright.shutdown_browser()
    except Exception:
        pass
