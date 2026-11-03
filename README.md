# nyabolag – weekly feed of newly registered Swedish companies

A micro-SaaS that sends local B2B sellers (accounting firms, insurance brokers, agencies) a weekly
CSV of companies newly registered in their area, from Bolagsverket's free open data.

**Read the docs first. The business case is a hypothesis until customers pay.**

| Doc | Contents |
|---|---|
| [docs/01-market-research.md](docs/01-market-research.md) | 10 Swedish opportunities, evidence, scoring, ranking, recommendation |
| [docs/02-validation-plan.md](docs/02-validation-plan.md) | Phase 0–3 validation with kill criteria, interview script, outreach template |
| [docs/03-product-and-economics.md](docs/03-product-and-economics.md) | Product scope, architecture, costs, customers needed for 1,000 SEK/month |

## Status

- Working MVP: parser → snapshot diff → filters → CSV/email delivery → Stripe subscription webhooks →
  magic-link dashboard → `/healthz` + healthcheck pings. 12 tests pass.
- **Not yet verified against a real Bolagsverket file** (this was built without network access to
  bolagsverket.se). The parser finds columns by header name (`COLUMN_ALIASES` in `nyabolag/bulkfile.py`).
  Validation Phase 0 starts with `python -m nyabolag inspect bolagsverket_bulkfil.zip`.

## Quick start (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q

export NYABOLAG_DATA_DIR=./data
.venv/bin/python -m nyabolag ingest tests/fixtures/bulk_week1.txt      # baseline
.venv/bin/python -m nyabolag ingest tests/fixtures/bulk_week2.zip      # diff → 4 new
.venv/bin/python -m nyabolag export --cities "Göteborg,Mölndal" --out sample.csv
.venv/bin/python -m nyabolag serve --debug                             # http://127.0.0.1:5000
```

Without `SMTP_HOST`, emails are written to `data/outbox/*.eml`.

## Validation-stage workflow (no web app needed)

1. `nyabolag fetch` then `nyabolag ingest <file>` weekly, and `nyabolag stats` for volume per postcode area.
2. `nyabolag export --postcodes 411,412 --out gbg.csv` → email it as a free sample.
3. A prospect pays via a Stripe **Payment Link** → `nyabolag add-customer kund@firma.se --postcodes 411,412`.
4. `nyabolag deliver` (or `run-weekly`) sends the weekly CSV to every active customer.

## Production (one small VPS)

1. `useradd -r nyabolag`, clone to `/opt/nyabolag`, create the venv, `cp deploy/.env.example /etc/nyabolag.env` and fill it in.
2. Stripe: create a product with a recurring price (249 SEK/month), enable the customer portal, and add a webhook to
   `https://<domain>/stripe/webhook` for `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted` and `invoice.payment_failed`.
3. Install `deploy/*.service`, `deploy/nyabolag-weekly.timer` and `deploy/Caddyfile`, then
   `systemctl enable --now nyabolag-web nyabolag-weekly.timer`.
4. Monitoring: point UptimeRobot (free) at `/healthz`, which returns 503 when data is more than 9 days old. Set
   `HEALTHCHECK_URL` so a missed or failed weekly run alerts you. Failures also email `ADMIN_EMAIL`.
5. Backups: back up `/var/lib/nyabolag` (SQLite + delivered CSVs) through VPS snapshots or nightly `sqlite3 .backup`.

## Known limitations / next steps

- CSRF protection relies on `SameSite=Lax` cookies. Add tokens before adding more state-changing forms.
- Not yet implemented: the *reklamspärr* join from SCB's free company register (planned in validation Phase 0).
- One filter per customer. No contact enrichment.
