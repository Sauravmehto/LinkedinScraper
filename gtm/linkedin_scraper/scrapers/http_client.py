"""
HTTP client for company websites (Steps 1 & 2).

Uses httpx with redirects, compression, and a browser-like User-Agent.
Each call creates a short-lived client (safe for ThreadPoolExecutor workers).
"""

from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_url(url: str, timeout: float = 15.0) -> str | None:
    """
    GET *url* and return response text, or None on network/HTTP errors.

    Follows redirects (e.g. http → https). Does not execute JavaScript.
    """
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=DEFAULT_HEADERS,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except (httpx.HTTPError, TimeoutError, OSError):
        return None
