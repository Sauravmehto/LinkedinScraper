#!/usr/bin/env python3
"""GTM LinkedIn scraper — single entry point."""

from __future__ import annotations

import sys

from gtm.linkedin_scraper.cli import main

if __name__ == "__main__":
    sys.exit(main())
