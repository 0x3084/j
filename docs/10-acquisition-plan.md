# 10. Customer acquisition plan: the first 5 paying customers

**Goal:** 5 accounting firms in Norrköping and Linköping paying 249 SEK/month. Time box: **6 weeks** from the first call.

**Budget:** 0 SEK. Your time: about 2–3 hours/week.

**Rule:** nobody is contacted until you approve it. Every contact is made by you, manually.

## Why this segment, and what we don't know yet
- **Accounting firms:** they get the most value per company (one new bookkeeping client is worth thousands of SEK/month) and are easy to find.
- **Volume:** about 11 new companies a week in each city (verified for Sept–Oct 2026).
- **Unknown:** whether firms actually win clients this way, and whether they will pay. This plan exists to find out cheaply. Every number below marked *assumption* is a guess to be replaced by your own results.

## The funnel (assumptions to measure)

| Step | Assumed rate | From 30 firms |
|---|---|---|
| Reached the right person (phone; 2 attempts) | 60 % | 18 |
| Interested in a free sample | 50 % | 9 |
| Paid after the sample + 1 follow-up | 40 % | **≈ 4** |

So you need about **30–40 firms** in the list. `07-prospects.md` has 20 (14 in Norrköping/Linköping). Add 15–20 more from hitta.se / eniro.se ("redovisningsbyrå Norrköping", "redovisningsbyrå Linköping"), using the same columns. Prefer small, owner-run firms. **Check the company form**: sole traders get phone or letter only, never cold email.

## Offer
- **Free:** last month's list for their municipality, as the privacy-safe sample report, plus one week of the real list after a verbal "yes, send it".
- **Paid:** 249 SEK/month, no lock-in. Payment either:
  - by **Stripe Payment Link**, monthly card payment (requires activating Stripe: your decision, doc 13 step 8), or
  - by **invoice per quarter in advance** (747 SEK). Many Swedish firms prefer an invoice. For 5 customers that's 5 invoices a quarter, from a free invoicing tool or a template.
- **No discount by default.** If price is the only objection: 199 SEK/month for the first 3 months, then 249. (A permanent 199 needs 6 customers to reach 1,000 SEK of profit; see doc 06.)

## Week by week

| Week | You do | Output |
|---|---|---|
| 0 (prep) | Doc 13 steps 1–7: official data verified, reklamspärr verification running, business registered, terms and privacy text written | Sample PDF per city, ready to send |
| 1 | Call the **7 A-prospects** (doc 11 scripts). Send the sample within 1 hour of each "yes". Log every call | 5–7 calls, 2–4 samples |
| 2 | Follow up the samples by phone ("did you look at it? can I send next Monday's real list?"). Call 8 more firms | First trial week(s) |
| 3 | After a trial list: ask for payment. Call 8 more | **First paying customer** (target) |
| 4–5 | Same rhythm. Ask paying customers for one referral ("know another firm that would want this?") | 3–5 paying |
| 6 | **Decision** (below) | Go / iterate / stop |

## What you track (spreadsheet, one row per firm)
Firm · city · company form · date called · reached (y/n) · interested (y/n) · sample sent · trial list sent · paid (y/n, date) · price · **reason for "no" in their own words** · do-not-contact (y/n).

## Decision rules at week 6

| Result | Decision |
|---|---|
| ≥ 3 paying | **Go:** move the weekly job to a small VPS (doc 13 step 11), keep calling until 5 |
| 1–2 paying | Iterate for 3 more weeks on the most common "no" reason (price → quarterly invoice; content → add SNI industry code; area → add Mjölby, Motala, Söderköping) |
| 0 paying after 30 conversations | Stop this segment. Test insurance brokers or banks with the same sample, or switch to procurement alerts (doc 01, rank 2) |

## Keeping it low-touch once customers pay
- **Monday/Tuesday routine:** about 5 minutes for fetch → ingest → verify → export per customer → email (doc 09 G). After ≥ 3 customers, the VPS job does the same automatically.
- **Churn:** each month, ask every customer one question: "Har ni fått någon kund via listan?" Note the answer. Cancellations are expected; keep about 1 new call a week.
