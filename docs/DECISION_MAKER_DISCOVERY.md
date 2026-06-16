# Decision-Maker Discovery

This document describes the Phase 2 pipeline that discovers decision makers (`linkedin.com/in/...`) for each company.

## Purpose

The company pipeline finds company LinkedIn URLs.  
The people-discovery pipeline finds relevant decision-maker profiles with scoring and confidence labels.

## Pipeline (free-first, quality-gated)

1. Classify company type using company name + website domain (+ optional `Company Type` column)
2. Expand role targets from role maps
3. **Disk cache** — reuse prior hits for same company (`--use-people-cache`, `--refresh-cache`)
4. **Free tier:** team pages (httpx, **Firecrawl fallback** on JS-heavy pages) → **Bing first** → DDG only if Bing quality &lt; 2
5. **Serper** (free tier, 2,500/mo) — only if quality &lt; `--apollo-sufficient-hits` (default 3)
6. **Quality gate** — count profiles with valid `/in/` URL + name/title signals (not raw URL count; email not required)
7. **Apollo** (paid) — only if quality still &lt; 3; includes `work_email` when available
8. **Tavily** (paid) — only if quality still &lt; `--min-people-before-tavily` (default 2)
9. Dedupe by URL + name
10. Optional **Anthropic** filter/rank — only when messy sources (bing/ddg/serper/tavily) or junk names need cleanup
11. Score (email/name bonuses), cap **5 per company**

Order: **free → Serper → Apollo → Tavily → dedup → Anthropic**. Fallbacks use **quality profile count**, not raw hit count.

**Note:** Brave is **not** used for people discovery (company LinkedIn Step 5 only). Run `--refresh-cache` once after upgrading the pipeline.

## Output Schema

Sheet: `Decision Makers`

| Column | Description |
|--------|-------------|
| `company_name` | Company from input workbook |
| `company_type` | Classified type |
| `company_linkedin` | Company LinkedIn URL from company pipeline |
| `person_name` | Best-effort inferred profile name |
| `person_title` | Title signal used for ranking |
| `person_linkedin` | Candidate `linkedin.com/in/...` URL |
| `work_email` | Work email from Apollo when available |
| `email_status` | e.g. `from_apollo` |
| `source` | Source where candidate was found |
| `score` | Deterministic relevance score (0-100) |
| `confidence` | `HIGH`, `MEDIUM`, `LOW` |
| `role_target` | Target role bucket |
| `notes` | Extra metadata |

## Role Mapping

Role map is selected by company type and expanded with role variations.

Examples:
- `CFO` -> `Chief Financial Officer`, `Finance Director`, `Head of Finance`, `Controller`
- `COO` -> `Chief Operating Officer`, `Operating Partner`, `Head of Operations`
- `Investor Relations` -> `Head of IR`, `Investor Relations Director`, `IR Manager`

## Scoring Policy

Positive signals:
- company match in title/snippet
- role match (exact or variation)
- seniority terms (`CFO`, `Director`, `Partner`, etc.)
- finance/investment terms
- work email present (+15)
- real person name (+10)

Penalties:
- former/ex signals
- weak role evidence

Confidence bands:
- `HIGH >= 70`
- `MEDIUM 40-69`
- `LOW < 40`

## CLI

Discover people from an existing company-output workbook:

```powershell
python -m pipenv run python main.py discover-people `
  --input "output\result.xlsx" `
  --people-output "output\decision_makers.xlsx" `
  --enable-people-discovery `
  --max-people-per-company 5
```

### Max coverage mode (unlimited contacts)

```powershell
python -m pipenv run python main.py discover-people `
  --input "output\result.xlsx" `
  --people-output "output\decision_makers.xlsx" `
  --enable-people-discovery `
  --coverage-mode max `
  --refresh-cache
```

Max mode: Playwright team pages, all role queries on Bing/Serper, no per-company cap, dedupe only at end.

Run full company + people pipeline:

```powershell
python -m pipenv run python main.py run-full-intel --input "data\Sample file.xlsx" --output "output\result_final.xlsx" --people-output "output\decision_makers.xlsx" --steps 1,2,3 --enable-fallbacks --enable-people-discovery
```

## API Keys

Optional `.env` keys:

```env
SERPER_API_KEY=...    # people discovery (before Apollo)
FIRECRAWL_API_KEY=... # team/leadership pages (httpx fallback)
TAVILY_API_KEY=...
APOLLO_API_KEY=...
BRAVE_API_KEY=...     # company LinkedIn Step 5 only (not people)
PROXYCURL_API_KEY=...
ROCKETREACH_API_KEY=...
```

Missing keys are handled gracefully by skipping those sources.

## Performance and credit tips

- `--people-sources auto`: `bing,ddg,serper,apollo` (when keys set); Tavily = fallback only.
- `--max-people-per-company 5` — hard cap per company.
- `--apollo-sufficient-hits 3` — skip Apollo when **quality** free + Serper profiles ≥ 3.
- `--serper-fallback-queries 3` — max Serper queries per company when gated.
- `--skip-ddg-if-bing-quality 2` — skip redundant DDG calls.
- `--max-queries-per-company 8` — fewer free SERP queries (priority roles only).
- `--use-people-cache` / `--refresh-cache` — skip repeat API calls (cache under `output/cache/people/`).
- Logs: `quality=N`, `cache=hit|miss`, `serper=used(3)|skipped_sufficient`, `apollo=skipped_free_ok`, `tavily=skipped_sufficient`.
