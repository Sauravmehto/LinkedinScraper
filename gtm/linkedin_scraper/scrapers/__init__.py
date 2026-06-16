"""
GTM website scrapers — multi-step LinkedIn URL discovery.

Import ScrapeResult / scrape_company_website from scrapers.pipeline.
"""

from .pipeline import scrape_company_website
from .result import ScrapeResult

__all__ = ["ScrapeResult", "scrape_company_website"]
