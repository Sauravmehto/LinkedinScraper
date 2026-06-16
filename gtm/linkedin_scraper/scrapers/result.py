"""Shared scrape outcome type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScrapeResult:
    profile_url: Optional[str]
    method: str  # e.g. step1, not_found
    note: str  # human-readable detail for logs / Excel
