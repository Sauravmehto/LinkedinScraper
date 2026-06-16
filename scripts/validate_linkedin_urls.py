#!/usr/bin/env python3
"""Legacy wrapper — prefer: python main.py validate-linkedin ..."""

from __future__ import annotations

import sys

from gtm.linkedin_scraper.cli import main

if __name__ == "__main__":
    sys.exit(main(["validate-linkedin", *sys.argv[1:]]))
