# Final report (`final_report.xlsx`)

Consolidated HubSpot contact import file built from pipeline outputs, matching the layout of **Hubspot CD 20052026 1.xlsx**.

## Workflow

```
data/Sample file.xlsx
    → run-full-intel
    → output/result_final.xlsx
    → output/decision_makers_new.xlsx
    → build-final-report
    → output/final_report.xlsx
    → HubSpot Import  OR  sync-hubspot
```

## Command

```powershell
python -m pipenv run python main.py build-final-report `
  --template "output\Hubspot CD 20052026 1.xlsx" `
  --companies "output\result_final.xlsx" `
  --people "output\decision_makers_new.xlsx" `
  --output "output\final_report.xlsx"
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--template` | `output/Hubspot CD 20052026 1.xlsx` | HubSpot CD template (falls back to `data/` if missing) |
| `--companies` | `output/result_final.xlsx` | Company workbook for join |
| `--people` | `output/decision_makers_new.xlsx` | Decision-makers workbook |
| `--output` | `output/final_report.xlsx` | Generated report |
| `--min-score` | `55` | Minimum `score` column |
| `--require-email` / `--no-require-email` | email required | HubSpot-ready subset |
| `--require-phone` | off | Require `direct_dial` |
| `--lead-status` | `HUBSPOT_LEAD_STATUS` | Lead Status column |
| `--lifecycle-stage` | `HUBSPOT_LIFECYCLE_STAGE` | Lifecycle Stage column |
| `--owner-id` | `HUBSPOT_CONTACT_OWNER_ID` | Contact owner |
| `--dry-run` | off | Stats only, no file write |

### After `run-full-intel`

```powershell
python -m pipenv run python main.py run-full-intel `
  --input "data\Sample file.xlsx" `
  --output "output\result_final.xlsx" `
  --people-output "output\decision_makers_new.xlsx" `
  --enable-people-discovery --enable-contact-enrichment `
  --coverage-mode max `
  --build-final-report
```

## Column mapping (template → GTM)

Template headers are read from row 1; values are written by **header name** (case-insensitive).

| Template column | Source |
|-----------------|--------|
| First Name | `person_name` (first word) |
| Last Name | `person_name` (remainder) |
| Email | `work_email` |
| Job Title | `person_title` or `role_target` |
| Company Name | `company_name` |
| Website URL | `company_website` or company `Official Website` |
| Linkedin account | `person_linkedin` |
| LinkedIn Company Page | `company_linkedin` or company `Profile URL` |
| Mobile Phone Number | `direct_dial`, else `hq_phone` (from Apollo person/org, company Excel, or peer backfill) |
| Lead Status | `.env` / `--lead-status` |
| Lifecycle Stage | `.env` / `--lifecycle-stage` |
| Contact owner / Communication Owner | `.env` / `--owner-id` |
| Country/Region | Company `Country` from `result_final` |
| Associated Note | Score, source, role, LinkedIn URLs, AUM/focus from company row |
| City, State/Region, Persona, conversion dates | Left blank |

## Filter and dedupe

1. Valid person LinkedIn (`/in/` URL)
2. `score >= --min-score`
3. `work_email` present (unless `--no-require-email`)
4. Optional `--require-phone`
5. Dedupe by LinkedIn URL (keep highest score)
6. Dedupe by email (keep highest score)

## Company join

Companies are matched by **exact** company name (case-insensitive). Names that differ slightly (e.g. "Clarion Partners" vs "Clarion Partners LLC") may not join; website/company LinkedIn on the people row still apply.

## vs `sync-hubspot`

| | `final_report.xlsx` | `sync-hubspot` |
|--|---------------------|----------------|
| Output | Excel for import/review | Live CRM API |
| Layout | Your HubSpot CD template | HubSpot properties |
| Email | Filtered by default | Required for upsert |

Use both: generate the report for review, then `sync-hubspot` for automation.
