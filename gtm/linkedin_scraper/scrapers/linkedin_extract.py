"""
LinkedIn URL detection shared across scrape steps.

Parses company-site HTML only — we do not scrape linkedin.com itself.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Prefer /company/ pages; also allow /in/ and /school/
LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[a-zA-Z0-9_%\-\.]+/?",
    re.IGNORECASE,
)


def normalize_website(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url or url.lower() in ("n/a", "na", "-", "none"):
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def clean_linkedin_url(url: str) -> str:
    return url.rstrip("/").split("?")[0].split("#")[0]


def pick_best_linkedin(urls: list[str]) -> Optional[str]:
    if not urls:
        return None
    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        u = clean_linkedin_url(u)
        key = u.lower()
        if key not in seen:
            seen.add(key)
            unique.append(u)
    for u in unique:
        if "/company/" in u.lower():
            return u
    return unique[0]


def extract_from_html(html: str) -> Optional[str]:
    """Regex scan of raw HTML (scripts, JSON, comments)."""
    return pick_best_linkedin(LINKEDIN_RE.findall(html))


def _href_to_absolute(href: str, base_url: str) -> Optional[str]:
    href = (href or "").strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    return urljoin(base_url, href)


def extract_from_soup(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Collect LinkedIn URLs from all <a href> on the page."""
    candidates: list[str] = []
    for tag in soup.find_all("a", href=True):
        absolute = _href_to_absolute(tag["href"], base_url)
        if absolute and "linkedin.com" in absolute.lower():
            candidates.append(absolute)
    return pick_best_linkedin(candidates)


def extract_linkedin_from_page(html: str, base_url: str) -> Optional[str]:
    """Step 1 parser: anchor tags first, then full-page regex fallback."""
    soup = BeautifulSoup(html, "lxml")
    found = extract_from_soup(soup, base_url)
    if found:
        return found
    return extract_from_html(html)


# href="...", href='...', and similar attributes in inline HTML/JSON
HREF_LINKEDIN_RE = re.compile(
    r"""href\s*=\s*["']([^"']*linkedin\.com[^"']*)["']""",
    re.IGNORECASE,
)


def extract_deep_from_page(html: str, page_url: str) -> Optional[str]:
    """
    Step 2 parser: all anchor hrefs, href= attributes in markup, then full HTML regex.
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []

    for tag in soup.find_all("a", href=True):
        absolute = _href_to_absolute(tag["href"], page_url)
        if absolute and "linkedin.com" in absolute.lower():
            candidates.append(absolute)

    for match in HREF_LINKEDIN_RE.findall(html):
        absolute = _href_to_absolute(match, page_url)
        if absolute and "linkedin.com" in absolute.lower():
            candidates.append(absolute)

    found = pick_best_linkedin(candidates)
    if found:
        return found
    return extract_from_html(html)


def same_registrable_host(url: str, base_url: str) -> bool:
    """True if *url* belongs to the same host as *base_url* (www. ignored)."""
    a = urlparse(url).netloc.lower().removeprefix("www.")
    b = urlparse(base_url).netloc.lower().removeprefix("www.")
    return bool(a) and a == b
