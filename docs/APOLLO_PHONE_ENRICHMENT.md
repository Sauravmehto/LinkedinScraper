# Apollo phone enrichment (`enrich-phones`)

Apollo returns phone numbers **asynchronously** when `reveal_phone_number=true`. You must provide `webhook_url`; this CLI **polls** `webhook_results/poll` until phones arrive or timeout.

## Setup

1. Create a public HTTPS webhook URL (testing: [webhook.site](https://webhook.site) → copy your unique URL)
2. Add to `.env`:

```env
APOLLO_WEBHOOK_URL=https://webhook.site/your-uuid-here
APOLLO_PHONE_POLL_TIMEOUT=120
APOLLO_PHONE_POLL_INTERVAL=5
```

3. Ensure `APOLLO_API_KEY` is set.

## Commands

```powershell
# Preview eligible rows
python -m pipenv run python main.py enrich-phones --dry-run --limit 5

# Enrich phones (poll until received or timeout)
python -m pipenv run python main.py enrich-phones `
  --input "output\decision_makers_new.xlsx" `
  --only-missing-phones `
  --limit 10

# Full run
python -m pipenv run python main.py enrich-phones `
  --input "output\decision_makers_new.xlsx"
```

## Excel columns updated

| Column | Meaning |
|--------|---------|
| `direct_dial` | E.164 phone from Apollo |
| `hq_phone` | Org phone if returned |
| `phone_source` | `apollo_sync`, `apollo_poll` |
| `phone_status` | `received`, `timeout`, `submit_error`, etc. |

## Cache

Pending jobs: `output/cache/apollo_phones/pending.json`  
Poll results: `output/cache/apollo_phones/results/{request_id}.json`

## Notes

- Skips rows that already have `direct_dial` (use `--no-only-missing-phones` to force)
- Phone reveal consumes Apollo credits
- After phones are filled, re-run `sync-hubspot` to push to HubSpot
