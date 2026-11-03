# 12. Audit: security, data protection and operational reliability (2026-11-03)

**Scope:** all code in `nyabolag/`, the `validation/` scripts, the `deploy/` files and the planned operating model (manual on your Mac now, a small VPS later).

**Method:** code review, the 20 automated tests, `pip-audit` on the pinned dependencies, and a real-data run (9,117 rows) plus a load test (500k rows).

Status legend: **Fixed** = changed in this commit and covered by a test where possible. **Open** = must be done before the stated milestone.

## Summary

| Severity | Fixed in this commit | Open before 1st paying customer | Open before VPS / web launch |
|---|---|---|---|
| High | 4 (D1, S1, S2, R1) | 2 (D6, S9) | – |
| Medium | 6 (D2, D3, D9, S3, R2, R3) | 2 (D7, R8) | 5 (D8, S5, S6, S7, R7) |
| Low | 5 (D5, D10, S4, R4, S10) | – | – |

D4 (c/o names, High) was fixed in the previous commit.

## Data protection

| # | Finding | Sev. | Status |
|---|---|---|---|
| D1 | Companies with unknown or stale reklamspärr could reach customers | High | **Fixed:** deliveries, the dashboard and `export` only include companies verified as not opted out within `REKLAMSPARR_MAX_AGE_DAYS` (30). Missing, stale or failed statuses are excluded (tests) |
| D2 | API evidence log stored full responses, including c/o names and addresses | Medium | **Fixed:** only org number, HTTP status, time and the raw flag are kept (test) |
| D3 | The database kept street addresses and descriptions for about 1.3 M older companies that are never delivered | Medium | **Fixed:** only new companies keep street and description (test) |
| D4 | c/o names (private persons) | High | Fixed earlier: never stored or exported |
| D5 | The Stripe webhook response echoed the customer's email | Low | **Fixed** |
| D6 | No written legitimate-interest assessment, privacy notice or customer terms | High | **Open (before 1st customer):** doc 05 checklist; templates in doc 13 step 6 |
| D7 | Objections ("remove my company") need a routine | Medium | **Open (before 1st customer):** add the org number to `reklamsparr` with `blocked=1, source='objection'` (one SQL line, doc 13). A CLI command can come later |
| D8 | Data processors: email provider, VPS host, Stripe | Medium | **Open (before VPS/web launch):** pick EU providers and accept their data processing agreements (DPAs). During validation you use your own mailbox and Mac |
| D9 | The prospect sample showed real names | Medium | **Fixed:** the prospect sample masks names and has no org numbers, addresses or postcodes |
| D10 | Retention | Low | **Fixed:** `nyabolag purge --days 365` (deliveries, evidence, old bulk files); runs in the weekly service |

## Security (web app; it is **not** deployed)

| # | Finding | Sev. | Status |
|---|---|---|---|
| S1 | Spreadsheet formula injection: register text starting with `=`, `+`, `-` or `@` would run as a formula in Excel | High | **Fixed:** such cells are prefixed with `'` (test) |
| S2 | A default `SECRET_KEY` could reach production | High | **Fixed:** the app refuses to start on https with a dev or short key |
| S3 | Missing security headers | Medium | **Fixed:** CSP, `nosniff`, `Referrer-Policy: no-referrer` (magic-link tokens are in URLs), `no-store` on account pages. Add HSTS in Caddy |
| S4 | Malformed Stripe metadata filters | Low | **Fixed:** normalised on import |
| S5 | Magic links can be reused within their 1-hour validity | Medium | **Open (before web launch):** make them single-use (store the last-login timestamp in the token) |
| S6 | No rate limit on `/login` or `/checkout` (email bombing, Stripe session spam) | Medium | **Open (before web launch):** Caddy `rate_limit` or a small per-IP limiter |
| S7 | CSRF relies on `SameSite=Lax` cookies only | Medium | **Open (before web launch):** add CSRF tokens to the 3 POST forms |
| S8 | Dependencies | – | Pinned in `requirements.txt`; `pip-audit`: no known vulnerabilities (2026-11-03). Re-run monthly |
| S9 | Secrets (Stripe keys, HVD client secret, SMTP) | High | Rule: only in `.env` (Mac, `chmod 600`) or `/etc/nyabolag.env` (VPS, root-owned, `chmod 600`). Never in git, chat or email. `.env` is git-ignored. **Open:** rotate any secret that has ever been pasted elsewhere |
| S10 | The HVD token error could log the server's response | Low | Fixed: only the HTTP status is logged |

## Operational reliability

| # | Finding | Sev. | Status |
|---|---|---|---|
| R1 | Unverified companies dropped from a delivery are never re-sent | High | **Fixed by ordering:** `run-weekly` is fetch → ingest → **verify** → deliver, and **aborts all deliveries if more than 5 % of lookups fail** (test), with an alert. Manual routine (doc 09 G) has the same order |
| R2 | Bolagsverket format change | Medium | **Fixed:** the job aborts on 0 parsed rows or more than 1 % malformed rows; the header is checked by name |
| R3 | Two runs overlapping (timer + manual) | Medium | **Fixed:** file lock |
| R4 | A wrong download URL saves an HTML page | Low | **Fixed:** non-zip downloads are rejected |
| R5 | Memory and time on the full file | – | Verified: streaming, 500k rows in 5 s at 26 MB RAM ⇒ about 30–60 s for the full file |
| R6 | Single point of failure: your Mac during validation | Medium | Accepted for ≤ 5 customers. Time Machine plus FileVault. If the Mac is away on a Tuesday, deliver Wednesday and tell customers |
| R7 | Bolagsverket reportedly blocks some foreign datacenter IPs (one unverified report) | Medium | **Open (before VPS):** test `fetch` and one HVD lookup from the chosen VPS before moving. Prefer a Swedish or Nordic datacenter |
| R8 | HVD token host is uncertain (`portal.api…` vs `gw.api…`) | Medium | **Open (before 1st customer):** configurable via `HVD_TOKEN_URL`; confirm against the email/portal and do the 3-lookup test (doc 09 E) |
| R9 | Monitoring | – | `/healthz`, Healthchecks.io ping on success/failure, admin email on failure (VPS phase) |

## Not checked / limits of this audit
- **No penetration test**, and no review of Stripe account settings (not activated). Caddy/TLS configuration is untested.
- **Legal points** (licence, legitimate-interest balance, VAT exemption) are practical reviews, not legal advice; see doc 05.
