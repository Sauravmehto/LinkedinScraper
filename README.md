# GTM — LinkedIn profile scraper

Python tooling to scrape LinkedIn company/profile URLs from REIT asset manager websites, validate results, and write an enriched Excel file.

## Prerequisites

- **Python 3.14** (see `Pipfile`)
- **Pipenv** — use `python -m pipenv` if `pipenv` is not on PATH

## Setup

```powershell
cd GTM
python -m pipenv install
python -m pipenv run playwright install chromium
```

## Primary command (recommended)

Run the full company pipeline in one step: scrape → validate LinkedIn → validate websites.

```powershell
python -m pipenv run python main.py run-all `
  --input "data\Sample file.xlsx" `
  --output "output\result_final.xlsx" `
  --steps 1,2,3 --force --enable-fallbacks

# Full intelligence run (company + decision makers)
python -m pipenv run python main.py run-full-intel `
  --input "data\Sample file.xlsx" `
  --output "output\result_final.xlsx" `
  --people-output "output\decision_makers.xlsx" `
  --steps 1,2,3 --force --enable-fallbacks --enable-people-discovery
```

- **`--input`** — source Excel (never modified)
- **`--output`** — enriched result file (optional; default: `output/<filename>_enriched.xlsx`)
- Close Excel before running or you will get a `PermissionError` on save

Dry run (first 2 rows, no file written):

```powershell
python -m pipenv run python main.py run-all `
  --input "data\Sample file.test.xlsx" `
  --output "output\test_final.xlsx" `
  --steps 1,2,3 --enable-fallbacks --limit 2 --dry-run
```

## Individual subcommands

```powershell
# Scrape only
python -m pipenv run python main.py scrape `
  --input "data\Sample file.xlsx" `
  --output "output\result.xlsx" `
  --steps 1,2,3 --force --enable-fallbacks

# Validate LinkedIn Profile URLs
python -m pipenv run python main.py validate-linkedin `
  --input "output\result.xlsx" `
  --output "output\result_validated.xlsx"

# Validate Official Website URLs
python -m pipenv run python main.py validate-websites `
  --input "output\result.xlsx" `
  --output "output\result_final.xlsx"

# Discover decision makers only (linkedin.com/in profiles)
python -m pipenv run python main.py discover-people `
  --input "output\result_final.xlsx" `
  --people-output "output\decision_makers.xlsx" `
  --enable-people-discovery --max-people-per-company 5
```

See all options:

```powershell
python -m pipenv run python main.py --help
python -m pipenv run python main.py run-all --help
```

For a short non-technical overview (steps, flow diagram, stack), see [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Project layout

```
GTM/
├── main.py                          # CLI entry point
├── gtm/linkedin_scraper/
│   ├── cli.py                       # Subcommands: scrape, validate-*, run-all
│   ├── io_utils.py                  # Excel read/write, sheet detection
│   ├── scrape.py                    # Scrape orchestration
│   ├── scrapers/                    # Steps 1–3 (httpx, deep links, Playwright)
│   ├── fallbacks/                   # Steps 4–9 fallback discovery
│   ├── people_discovery/            # Decision-maker discovery pipeline
│   └── validators/
│       ├── linkedin_urls.py         # Profile URL syntax + HTTP check
│       └── official_websites.py     # Official Website HTTP check
├── data/                            # Input Excel files
├── output/                          # Generated results (gitignored)
└── scripts/                         # Legacy wrappers (optional)
```

## Excel columns

| Column | Added by | Meaning |
|--------|----------|---------|
| `Official Website` | Input (required) | Company website to scrape |
| `Profile URL` | Scrape | LinkedIn company/profile URL found |
| `Scrape Method` | Scrape | `step1`, `step2`, `step3`, or fallback tags `step4_bing`..`step9_apollo` |
| `URL Valid (syntax)` | Validate LinkedIn | `yes` / `no` |
| `URL Status (live)` | Validate LinkedIn | `OK`, `OK (redirect)`, `404`, `blocked`, `timeout` |
| `Website Status` | Validate websites | HTTP status of Official Website |
| `Website Final URL` | Validate websites | URL after redirects |

Decision maker output (`output/decision_makers.xlsx`, sheet `Decision Makers`):

| Column | Meaning |
|--------|---------|
| `company_name` | Company from input row |
| `company_type` | Classified type (`PE`, `REIT`, etc.) |
| `company_linkedin` | Company LinkedIn URL from company pipeline |
| `company_website` | Official website (for Hunter/domain tools in later phases) |
| `person_name` | Best-effort extracted profile name |
| `person_title` | Role/title signal used for ranking |
| `person_linkedin` | Candidate `linkedin.com/in/...` URL |
| `work_email` | Work email (Apollo when available) |
| `email_confidence` | e.g. `from_apollo`, `verified` (Sprint 3+) |
| `email_status` | e.g. `from_apollo` |
| `direct_dial` | Person direct phone (Apollo `phone_numbers`) |
| `hq_phone` | Company HQ phone from Apollo org |
| `ir_email` / `ir_phone` | Investor relations contacts (Sprint 3+) |
| `phone_source` | Where phone was found (e.g. `apollo`) |
| `source` | Discovery source (`team_page`, `bing`, `ddg`, `serper`, `tavily`, `apollo`) |
| `score` / `confidence` | Deterministic relevance score and band |
| `role_target` | Target role bucket |
| `notes` | Additional metadata |

## Scrape pipeline

| Step | Method | When |
|------|--------|------|
| 1 | httpx + BeautifulSoup on homepage | Default |
| 2 | Deep href scan + `/about`, `/contact` | Default with Step 1 |
| 3 | Playwright (headless Chromium) | JS-heavy sites; use `--steps 1,2,3` |
| 4 | Bing search fallback | Only when `--enable-fallbacks` and unresolved after Step 3 |
| 5 | Brave Search API fallback | Optional API key (`BRAVE_API_KEY`) |
| 6 | DuckDuckGo fallback | Free backup search |
| 7 | Team/About/People targeted pages | Same-domain static fallback |
| 8 | Tavily API fallback | Optional API key (`TAVILY_API_KEY`) |
| 9 | Apollo API fallback | Optional API key (`APOLLO_API_KEY`), last resort |

## Decision-maker pipeline (Phase 2)

This pipeline discovers `linkedin.com/in/...` profiles for decision makers.

**Source waterfall (default):** team pages (httpx + Firecrawl + optional Playwright) → Bing → Serper → Apollo → Tavily → dedup → optional Anthropic.

**Max coverage:** add `--coverage-mode max` for unlimited contacts, expanded roles, Playwright team pages, and higher query budgets.

**Defaults:** max 5 people/company; quality-gated fallbacks; disk cache on; Apollo emails in `work_email`.

```powershell
python -m pipenv run python main.py discover-people `
  --input "output\result_final.xlsx" `
  --people-output "output\decision_makers.xlsx" `
  --enable-people-discovery `
  --enable-contact-enrichment
```

## Contact enrichment (Phase 3 — Sprint 1–2)

Fills **work email**, **direct_dial**, and **hq_phone** via Apollo `people/match` (by LinkedIn URL + company domain). After match, **hq_phone** is backfilled from Apollo organization enrich (by `Official Website` domain), optional HQ phone columns on `result_final.xlsx`, and any peer row at the same company. Skips rows that already have email and phone unless `--enrich-all-contacts`.

```powershell
# Re-enrich an existing decision_makers file (no re-discovery)
python -m pipenv run python main.py enrich-contacts `
  --input "output\decision_makers.xlsx" `
  --companies-input "output\result_final.xlsx" `
  --output "output\decision_makers.xlsx"
```

## Final report (HubSpot CD Excel)

Merges `result_final.xlsx` + `decision_makers_new.xlsx` into one import file matching your **Hubspot CD** template layout (`output/final_report.xlsx`). Default: only contacts with `work_email` and `score >= 55`.

```powershell
python -m pipenv run python main.py build-final-report `
  --companies "output\result_final.xlsx" `
  --people "output\decision_makers_new.xlsx" `
  --template "output\Hubspot CD 20052026 1.xlsx" `
  --output "output\final_report.xlsx"

# Or auto-build after a full intel run:
python -m pipenv run python main.py run-full-intel `
  --input "data\Sample file.xlsx" `
  --output "output\result_final.xlsx" `
  --people-output "output\decision_makers_new.xlsx" `
  --enable-people-discovery --enable-contact-enrichment `
  --coverage-mode max --build-final-report
```

See [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md) for column mapping and filters.

## HubSpot CRM sync

Requires a **Private App** access token in `.env` as `HUBSPOT_ACCESS_TOKEN` (format `pat-na2-...`).

```powershell
# Preview (no API writes)
python -m pipenv run python main.py sync-hubspot --dry-run

# Sync decision makers + companies to HubSpot
python -m pipenv run python main.py sync-hubspot `
  --people "output\decision_makers_new.xlsx" `
  --companies "output\result_final.xlsx"
```

Contacts **must have `work_email`** to sync (upsert by email). Rows without email are skipped. Companies are matched by domain, then name.

## Optional API keys (.env)

Create `.env` at repo root only if you want API-backed fallbacks:

```env
SERPER_API_KEY=your_serper_key   # people discovery (before Apollo)
FIRECRAWL_API_KEY=your_firecrawl_key  # team pages when httpx fails
TAVILY_API_KEY=your_tavily_key
APOLLO_API_KEY=your_apollo_key
BRAVE_API_KEY=your_brave_key     # company LinkedIn Step 5 only
PROXYCURL_API_KEY=optional_future
ROCKETREACH_API_KEY=optional_future
```

If a key is missing, that API fallback step is skipped gracefully.

## Decision-maker discovery

- Package: `gtm/linkedin_scraper/people_discovery`
- Workflow: classify company type -> expand role map -> scrape team pages -> query/search -> extract `linkedin.com/in` -> score -> output workbook
- Sources are configurable with `--people-sources` and API-key gated where applicable
- Detailed design doc: [docs/DECISION_MAKER_DISCOVERY.md](docs/DECISION_MAKER_DISCOVERY.md)

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| `pipenv` not found | Use `python -m pipenv install` and `python -m pipenv run ...` |
| PermissionError on save | Close the output `.xlsx` in Excel |
| Sheet not found | Use `--sheet "Sheet1"` or ensure `Official Website` column exists |
| LinkedIn returns `blocked` | Bot protection — URL may still be valid in a browser |
| Playwright missing | `python -m pipenv run playwright install chromium` |
