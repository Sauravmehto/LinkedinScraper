"""Data types shared by fallback search steps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LinkedInCandidate:
    url: str
    source: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class FallbackResult:
    profile_url: str | None
    method: str
    note: str
