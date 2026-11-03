# 3. Minimal product, operations and unit economics

Working name: **nyabolag**. Check trademarks and domains before choosing a public name.

## Product (what a customer gets)

- **Every Monday:** an email with a CSV (Excel-friendly, `;`-separated, UTF-8 BOM) listing the companies newly registered since the last delivery that match their filter.
- **Filter:** postcode prefixes and/or towns, company forms (AB by default), optional keywords in the business description.
- **Dashboard** (magic-link login, no passwords): subscription status, edit filter, preview of how many companies matched in the last 4 weeks, download of past deliveries, "Hantera betalning" (Stripe customer portal for card, receipts and cancelling).
- **Price:** 249 SEK/month ex. moms, monthly, no lock-in. Founding price 199 SEK for the first 5 customers.

**Out of scope for the MVP:** contact enrichment (email/phone), multiple filters per account, an API, invoicing by "faktura" (add it when a customer asks; Stripe can send invoices).

## Architecture (one VPS, one developer)

```
systemd timer (Mon 06:00) ──> nyabolag run-weekly
        fetch bulk file (Bolagsverket HVD, weekly, free)
        ingest → SQLite (diff vs previous snapshot = new companies)
        deliver → per active customer: filter → CSV → email
        ping healthcheck (success / fail) ; email admin on error

gunicorn + Flask (behind Caddy, auto-HTTPS)
        /            landing + signup → Stripe Checkout (subscription)
        /stripe/webhook  checkout.session.completed / subscription.updated|deleted / invoice.payment_failed
        /login, /auth/<token>  magic link
        /dashboard   status, filters, deliveries, billing portal
        /healthz     503 if last successful ingest > 9 days old (external uptime monitor watches it)
```

Design choices:
- **SQLite + one process.** The data is small: the bulk file is about 1M+ rows, the stored companies table about 300 MB at most, and only new companies matter for delivery.
- **Stripe is the source of truth for billing.** The app only mirrors `status` from webhooks, which are stored by event id so they're idempotent.
- **Deliveries are idempotent** per (customer, snapshot), so re-running the weekly job never double-sends.
- **The first ingest is a baseline:** nothing gets delivered from it. A company only counts as "new" when it is absent from the previous snapshot **and** its registration date (if present) is within the last 60 days.

## Operating costs (monthly, ex. VAT, taxes excluded; check current prices)

| Item | Estimate |
|---|---|
| VPS (e.g. Hetzner CX22-class, 2 vCPU/4 GB) + backups | about 60–75 SEK |
| Domain (.se, about 150–200 SEK/year) | about 15 SEK |
| Transactional email (Brevo/Postmark/SMTP free tier at < 300 mails/day) | 0 SEK at this scale |
| Uptime and cron monitoring (UptimeRobot / Healthchecks.io free tiers) | 0 SEK |
| **Fixed total** | **about 75–90 SEK/month** |
| Stripe, per charge (assumption: about 1.5 % + 1.80 SEK for EEA cards, plus Stripe Billing about 0.7 %; verify on stripe.com/se/pricing) | about 7.30 SEK per 249 SEK charge |

## Customers needed

Net per customer at 249 SEK: 249 − 7.30 ≈ **241.70 SEK**.

| Target | Formula | Customers |
|---|---|---|
| 1,000 SEK **gross** MRR | ⌈1000 / 249⌉ | **5** |
| 1,000 SEK MRR **after** fixed costs and Stripe | ⌈(1000 + 90) / 241.70⌉ | **5** (4.5) |
| Same, at the 199 SEK founding price | ⌈1090 / 194.1⌉ | 6 |
| Same, at 399 SEK (if interviews show low price sensitivity) | ⌈1090 / 390.4⌉ | 3 |

**Churn caveat:** lead lists tend to churn if the leads don't convert. If monthly churn is 10 %, keeping 5 customers means winning about 1 new customer every 2 months. Plan to keep doing light outreach indefinitely. This is a *mostly automated* business, not a passive one.

## Time budget (honest estimate)

- Validation: about 15–25 hours over 3 weeks.
- Turning the MVP in this repo into production (real file format fixes, deploy, Stripe live mode, legal pages): about 10–15 hours.
- Ongoing: about 1–2 hours/week for support and outreach, plus fixes if Bolagsverket changes the format.

## Legal checklist before charging money

- [ ] Registered business (enskild firma with F-skatt or AB). Charge 25 % moms on top.
- [ ] Terms of service and a privacy policy (customers' emails are personal data; delivered lists contain no private persons).
- [ ] Attribution and licence text for Bolagsverket/SCB data as their terms require.
- [ ] Exclude companies with *reklamspärr* if the SCB join is available. Document the legitimate-interest assessment for customer use.
