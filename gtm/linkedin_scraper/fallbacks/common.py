"""Common helpers for fallback search steps."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

from gtm.linkedin_scraper.scrapers.http_client import DEFAULT_HEADERS

LINKEDIN_COMPANY_LINK_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[a-zA-Z0-9_%\-\.]+/?",
    re.IGNORECASE,
)


def company_query(company: str, website: str = "") -> str:
    company = (company or "").strip()
    website = (website or "").strip()
    if website:
        return f'site:linkedin.com/company "{company}" "{website}"'
    return f'site:linkedin.com/company "{company}"'


def url_encode_query(query: str) -> str:
    return quote_plus(query)


def extract_company_urls(text: str) -> list[str]:
    return LINKEDIN_COMPANY_LINK_RE.findall(text or "")


def fetch_text(url: str, timeout: float = 15.0, headers: dict | None = None) -> str | None:
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


def post_json(
    url: str,
    payload: dict,
    timeout: float = 15.0,
    headers: dict | None = None,
) -> dict | None:
    try:
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=merged) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        return None
