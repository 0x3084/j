# nyabolag – weekly feed of newly registered Swedish companies

A micro-SaaS that sends local B2B sellers (accounting firms, insurance brokers, agencies) a weekly
CSV of companies newly registered in their area, from Bolagsverket's free open data.

**Read the docs first. The business case is a hypothesis until customers pay.**

| Doc | Contents |
|---|---|
| [docs/01-market-research.md](docs/01-market-research.md) | 10 Swedish opportunities, evidence, scoring, ranking, recommendation |
| [docs/02-validation-plan.md](docs/02-validation-plan.md) | Phase 0–3 validation with kill criteria, interview script, outreach template |
| [docs/03-product-and-economics.md](docs/03-product-and-economics.md) | Product scope, architecture, costs, customers needed for 1,000 SEK/month |
| [docs/04-real-data-validation.md](docs/04-real-data-validation.md) | Run on real Bolagsverket rows: format fixes, new-vs-reappeared, shelf companies, licence, reklamspärr |
| [docs/05-gdpr-and-direct-marketing.md](docs/05-gdpr-and-direct-marketing.md) | GDPR and marknadsföringslagen review, minimisation, checklist |
| [docs/06-profit-and-vat.md](docs/06-profit-and-vat.md) | Monthly profit after hosting, Stripe and VAT (momsbefrielse vs momsregistrering) |
| [docs/07-prospects.md](docs/07-prospects.md) | 20 potential customers in Norrköping, Linköping, Finspång (not contacted) |
| [docs/08-sales-pitch.md](docs/08-sales-pitch.md) | Swedish pitch: phone, email, objections |
| [docs/09-mac-setup-and-official-data.md](docs/09-mac-setup-and-official-data.md) | **On your Mac:** download the official file, verify the sample, import, verify reklamspärr, weekly routine |
| [docs/10-acquisition-plan.md](docs/10-acquisition-plan.md) | Plan for the first 5 paying customers, funnel assumptions, decision rules |
| [docs/11-sales-messages.md](docs/11-sales-messages.md) | Personalised Swedish messages for 10 firms (not sent) |
| [docs/12-security-privacy-reliability-audit.md](docs/12-security-privacy-reliability-audit.md) | Audit: what was fixed, what is open and when |
| [docs/13-your-steps-to-first-paying-customer.md](docs/13-your-steps-to-first-paying-customer.md) | **Start here:** your steps 1–14, plus privacy, terms and LIA templates |

Also: `site/index.html` (landing page, not published) and `validation/sample_report.py` (privacy-safe sample for accounting firms).

## Status

- **Not launched.** Stripe is not activated and nobody has been contacted.
- **Parser verified against 9,117 real rows** of Bolagsverket's weekly file of 2026-10-26, via a third-party
  copy, because this dev environment can't reach bolagsverket.se. See docs/04 for exactly what is and
  isn't verified.
- **Detection:** "new" means a recent `registreringsdatum`. Shelf companies (30 % of registrations) are excluded.
- **Reklamspärr:** only companies verified as not opted out in Bolagsverket's API within 30 days are ever delivered
  (`nyabolag verify-reklamsparr`). Missing, stale or failed statuses are excluded.
- **MVP:** parser → snapshot store → verify → filters → CSV/email delivery → Stripe webhooks → magic-link
  dashboard → `/healthz`. 20 tests pass; `pip-audit` is clean.

Re-run the sample report: `python validation/region_report.py out/ --file-date <date>` after
`nyabolag ingest <official zip> --as-of <date>` (and `nyabolag import-reklamsparr <API responses>`).

## Quick start (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q

export NYABOLAG_DATA_DIR=./data
.venv/bin/python -m nyabolag ingest bolagsverket_bulkfil.zip --as-of 2026-10-26
.venv/bin/python -m nyabolag stats
.venv/bin/python -m nyabolag export --cities "Linköping,Ljungsbro" --snapshots 1 --out sample.csv
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

- Open security items before any public web launch: see docs/12 (S5–S7, D8, R7).
- One filter per customer. No contact enrichment.
