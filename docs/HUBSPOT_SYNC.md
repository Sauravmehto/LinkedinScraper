# HubSpot CRM sync

## Which key to use?

| Type | Works with `sync-hubspot`? |
|------|----------------------------|
| **Private App** or **Service Key** (`pat-na2-...`) | **Yes — use this** |
| **Developer Personal Access Key** (long `CiRuYTI...` string) | **No** — HubSpot returns `401 OAuth token expired 20605 days ago` |
| Short UUID (`na2-60da-1704-...`) | **No** — not a token |

The **Personal Access Key** from the developer portal is only for **HubSpot CLI** (`hs` commands), not for `api.hubapi.com/crm/v3` contacts/companies.

## Setup (Private App — easiest for CRM)

1. HubSpot → **Settings** → **Integrations** → **Private Apps** → **Create private app**
2. Scopes (minimum):
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.companies.read`
   - `crm.objects.companies.write`
   - `crm.objects.notes.write` (optional; for import notes)
3. Copy the **access token** (starts with `pat-na2-` or `pat-na1-`)
4. Add to `.env`:

```env
HUBSPOT_ACCESS_TOKEN=pat-na2-your-full-token-here
```

Optional:

```env
HUBSPOT_CONTACT_OWNER_ID=12345678
HUBSPOT_LIFECYCLE_STAGE=lead
HUBSPOT_LEAD_STATUS=NEW
HUBSPOT_PROP_PERSON_LINKEDIN=linkedin_account
HUBSPOT_PROP_COMPANY_LINKEDIN=linkedin_company_page
```

Custom LinkedIn properties must exist in HubSpot before setting the `HUBSPOT_PROP_*` variables.

## Commands

```powershell
python -m pipenv run python main.py sync-hubspot --dry-run
python -m pipenv run python main.py sync-hubspot `
  --people "output\decision_makers_new.xlsx" `
  --companies "output\result_final.xlsx"
```

## Behavior

- **Companies** from `result_final.xlsx`: upsert by domain, then by name
- **Contacts** from decision-makers Excel: upsert by **email** (rows without `work_email` are skipped)
- Associates each contact to its company when the company was synced
- Adds a timeline **note** with score, source, and LinkedIn URLs (disable with `--skip-notes`)

## Column mapping (HubSpot template)

| HubSpot (your import sheet) | GTM field |
|-----------------------------|-----------|
| First Name / Last Name | `person_name` (split) |
| Email | `work_email` |
| Job Title | `person_title` |
| Company Name | `company_name` |
| Website URL | `company_website` |
| Linkedin account | `person_linkedin` (note + optional custom property) |
| LinkedIn Company Page | `company_linkedin` / company `Profile URL` |
| Mobile Phone Number | `direct_dial` or `hq_phone` |

## Troubleshooting

| Error | Fix |
|-------|-----|
| `401 Authentication credentials not found` | Wrong or incomplete token in `.env`. Use full **Private App** `pat-na2-...` **or** full **Personal Access Key** — not a short UUID |
| `403` / forbidden | Add **write** scopes (`crm.objects.contacts.write`, `crm.objects.companies.write`) |
| Property does not exist | Remove `HUBSPOT_PROP_*` or create the custom property in HubSpot |
| Many skipped contacts | Run `--enable-contact-enrichment` or `enrich-contacts` first |
