"""Fallback discovery steps used after Playwright misses."""

from .manager import FallbackStats, run_fallback_waterfall

__all__ = ["FallbackStats", "run_fallback_waterfall"]
