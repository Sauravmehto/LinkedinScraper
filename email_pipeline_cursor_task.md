# Task: Build Async Email Discovery Pipeline (Finance Firms)

## Project Goal
Build a Python async pipeline that takes a list of finance companies, discovers key decision-makers (CFO, MD, COO, etc.) via web scraping, and finds + verifies their work emails — cheaply and fast.

---

## Input
- Excel/CSV file with company names (14 rows to start, scalable to 1000+)
- Example row: `Blackstone`, `Clarion Partners`, `Heitman`

## Output
- Excel file with columns:
  ```
  company | person_name | title | person_linkedin | work_email | verified
  ```
- `verified` values: `✅ Valid`, `⚠️ Risky`, `❌ Invalid`

---

## Architecture: 3-Phase Async Pipeline

### Phase 1 — Find Company LinkedIn URL
**Goal:** Given a company name, find its official LinkedIn company page URL.

**Steps:**
1. Scrape Bing SERP: query = `"{company_name}" site:linkedin.com/company`
2. Parse result HTML with `selectolax` — extract first matching `linkedin.com/company/...` URL
3. Fallback: scrape company website (httpx) → look for LinkedIn icon/link in `<a>` tags
4. Return: `linkedin_url` string or `None`

**Tools:** `httpx` (async), `selectolax`
**Speed target:** ~0.8s per company
**Cost:** $0

---

### Phase 2 — Find 3–5 Decision Makers
**Goal:** For each company, find 3–5 senior finance decision-makers with LinkedIn profiles.

**Steps:**
1. Run parallel Bing SERP searches for each target role simultaneously:
   - `"{company_name}" CFO site:linkedin.com/in`
   - `"{company_name}" "Managing Director" site:linkedin.com/in`
   - `"{company_name}" COO site:linkedin.com/in`
   - `"{company_name}" "Head of" OR "VP" site:linkedin.com/in`
2. Parse results → extract: `name`, `title`, `linkedin_url`
3. Deduplicate by LinkedIn URL
4. Use Claude API to score/rank results — keep top 3–5 most relevant decision-makers
   - Prompt: "Given these search results for {company}, identify the 3-5 most senior finance decision-makers. Return JSON: [{name, title, linkedin_url}]"
5. Fallback: DuckDuckGo search if Bing returns nothing

**Tools:** `httpx` (async, parallel), `selectolax`, `anthropic` SDK
**Speed target:** ~1–2s per company (parallel)
**Cost:** ~$0.01/company (Claude scoring only)

---

### Phase 3 — Find & Verify Work Emails
**Goal:** For each person found in Phase 2, find and verify their work email.

**Steps (in order — stop at first success):**

**STEP 1 — Apollo Enrichment (Free tier: 50/mo)**
- Call Apollo People Enrichment API with `{name}` + `{company_domain}`
- If email returned → go to verification step
- API: `POST https://api.apollo.io/v1/people/match`

**STEP 2 — Bing/Google Search**
- Query: `"{first_name} {last_name}" "@{domain}"` 
- Also search: SEC filings, press releases, company website
- Extract any email pattern found

**STEP 3 — Hunter Pattern Detection (Free tier: 25/mo)**
- Call Hunter Domain Search API once per company (not per person)
- Extract the email pattern used by the company
- Cache in dict: `PATTERNS = {"blackstone.com": "firstname.lastname", ...}`
- API: `GET https://api.hunter.io/v2/domain-search?domain={domain}`

**STEP 4 — Email Generation**
- Use cached pattern to generate email for every person at that company
- Implement all common patterns:
  ```python
  PATTERNS = {
      "firstname.lastname":    f"{first}.{last}@{domain}",
      "firstinitial.lastname": f"{first[0]}.{last}@{domain}",
      "firstname":             f"{first}@{domain}",
      "firstnamelastname":     f"{first}{last}@{domain}",
      "f.lastname":            f"{first[0]}.{last}@{domain}",
  }
  ```
- All names → lowercase, strip accents/special chars before generating

**STEP 5 — MillionVerifier (Primary verifier)**
- Bulk verify generated emails
- API: `GET https://api.millionverifier.com/api/v3/?api={key}&email={email}`
- Response codes: `ok` = valid, `risky` = maybe, `invalid/error` = bad
- Cost: $0.0003/email

**STEP 6 — SMTP Verification (Free fallback)**
- Only used if MillionVerifier quota exhausted or API unavailable
- Use `dnspython` to resolve MX record, then `smtplib` to RCPT check
- Treat SMTP errors (550, 551, 553) as invalid; 250 as valid
- Note: some servers block SMTP probing — treat timeout as `None` (unknown)

---

## Code Structure

```
project/
├── main.py                  # Entry point, orchestrates pipeline
├── pipeline/
│   ├── phase1_linkedin.py   # Company LinkedIn URL finder
│   ├── phase2_people.py     # Decision-maker discovery
│   ├── phase3_email.py      # Email finding + verification
│   └── utils.py             # Shared helpers (name cleaning, dedup, etc.)
├── enrichment/
│   ├── apollo.py            # Apollo API client
│   ├── hunter.py            # Hunter API client + pattern cache
│   └── millionverifier.py   # MillionVerifier API client
├── scrapers/
│   ├── bing.py              # Bing SERP scraper (async)
│   ├── ddg.py               # DuckDuckGo fallback scraper
│   └── website.py           # Company website scraper
├── verification/
│   └── smtp.py              # SMTP email verifier (free fallback)
├── output/
│   └── excel_writer.py      # Write final Excel output
├── .env                     # API keys (never commit)
├── requirements.txt
└── README.md
```

---

## Async Concurrency Model

```python
# Process all companies in parallel (limit concurrency to avoid bans)
import asyncio

async def main():
    companies = load_excel("input.xlsx")
    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent companies
    
    async def bounded(company):
        async with semaphore:
            return await process_company(company)
    
    results = await asyncio.gather(*[bounded(c) for c in companies])
    write_excel(results, "output.xlsx")
```

- Use `httpx.AsyncClient` for all HTTP (not `requests`)
- Use `asyncio.gather` for parallel role searches in Phase 2
- Add random delays: `await asyncio.sleep(random.uniform(0.5, 1.5))` between Bing requests to avoid rate-limiting
- Rotate User-Agent headers on every Bing request

---

## Error Handling Rules

- Every API call wrapped in `try/except` with graceful fallback to next step
- If Phase 1 fails → log and skip company (don't crash pipeline)
- If Phase 2 finds 0 people → log warning, write empty row to Excel
- If Phase 3 finds no email → write `work_email = ""`, `verified = "❌ Not Found"`
- All errors logged to `pipeline.log` with company name + step + error message
- Never raise unhandled exceptions — pipeline must complete all companies

---

## Rate Limiting / Anti-Ban Strategy

- Bing scraping: random User-Agent rotation, 0.5–1.5s random delay between requests
- Hunter: cache domain patterns — call API **once per domain**, not per person
- Apollo: check remaining credits before each call; skip if exhausted
- MillionVerifier: batch emails per company into a single API call where possible

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=
APOLLO_API_KEY=
HUNTER_API_KEY=
MILLIONVERIFIER_API_KEY=
```

---

## Requirements (requirements.txt)

```
anthropic
httpx
selectolax
beautifulsoup4
lxml
playwright
duckduckgo-search
dnspython
pandas
openpyxl
python-dotenv
tqdm
```

---

## Cost & Speed Targets

| Scale | Time (with async) | Cost |
|-------|-------------------|------|
| 14 companies | ~2 min | ~$0.15 |
| 100 companies | ~5 min | ~$1.10 |
| 1000 companies | ~50 min | ~$11.00 |

- **Target success rate:** 85–95% email discovery
- **Free tier limit:** Apollo (50/mo), Hunter (25/mo) — pipeline must track usage and skip gracefully when exhausted

---

## Implementation Notes for Cursor

1. Start with `phase1_linkedin.py` — get Bing scraping working first with a single test company
2. Then `phase2_people.py` — parallel role searches, verify Claude scoring works
3. Then `phase3_email.py` — implement steps 1–6 in order, test each step independently
4. Wire everything in `main.py` last
5. Test with 3–5 companies before running the full 14-row file
6. Use `tqdm` progress bar in `main.py` to show pipeline progress
7. Write intermediate results to Excel after each company (don't wait until end — avoid data loss)
