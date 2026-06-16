"""
Step 2 — Deep link discovery (free, httpx only).

When: Step 1 did not find a LinkedIn URL on the homepage.
What:
  - Deeper parse of homepage (all href attributes + embedded href= in HTML)
  - Extra same-site pages: /about, /contact, etc. (see EXTRA_PATHS)
Does not: Leave the company domain or run JavaScript (see step3).
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from .http_client import fetch_url
from .linkedin_extract import (
    extract_deep_from_page,
    same_registrable_host,
)
from .result import ScrapeResult

# Same-domain paths commonly linked from footers (max requests controlled below)
EXTRA_PATHS: tuple[str, ...] = (
    "/about",
    "/about-us",
    "/aboutus",
    "/who-we-are",
    "/company",
    "/contact",
    "/contact-us",
    "/contactus",
    "/connect",
    "/social",
)

MAX_EXTRA_REQUESTS = 5


def _path_key(path: str) -> str:
    return path.rstrip("/").lower() or "/"


def _extra_urls(base_url: str) -> list[str]:
    """Build same-host URLs for common footer / about / contact paths."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    seen: set[str] = set()
    urls: list[str] = []
    for path in EXTRA_PATHS:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        urls.append(urljoin(origin + "/", path.lstrip("/")))
    return urls[:MAX_EXTRA_REQUESTS]


def _try_page(html: str, page_url: str, *, label: str) -> ScrapeResult | None:
    profile = extract_deep_from_page(html, page_url)
    if profile:
        return ScrapeResult(
            profile_url=profile,
            method="step2",
            note=f"step2: {label}",
        )
    return None


def run(
    base_url: str,
    timeout: float = 15.0,
    homepage_html: str | None = None,
) -> ScrapeResult:
    """
    Deep-scan homepage HTML, then fetch up to MAX_EXTRA_REQUESTS same-site paths.
  """
    html = homepage_html
    if html is None:
        html = fetch_url(base_url, timeout=timeout)

    if html:
        hit = _try_page(html, base_url, label="homepage deep")
        if hit:
            return hit
    else:
        # Homepage unreachable — still try /about and /contact on the same host
        pass

    for extra_url in _extra_urls(base_url):
        if not same_registrable_host(extra_url, base_url):
            continue
        page_html = fetch_url(extra_url, timeout=timeout)
        if not page_html:
            continue
        path = urlparse(extra_url).path or "/"
        hit = _try_page(page_html, extra_url, label=path)
        if hit:
            return hit

    if html is None:
        return ScrapeResult(
            profile_url=None,
            method="not_found",
            note="step2: fetch failed",
        )

    return ScrapeResult(
        profile_url=None,
        method="not_found",
        note="step2: no linkedin after deep scan",
    )
