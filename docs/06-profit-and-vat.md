# 6. Realistic monthly profit (before income tax)

Assumptions (check before relying on them):
- **Exchange rate:** EUR = 11.00 SEK.
- **Hosting:** Hetzner CX23 at €5.49/month (after the 2026 increases) + IPv4 €0.50 + backups 20 % of the server price (€1.10), so **€7.09 ≈ 78 SEK** ex VAT.
- **Domain:** .se at about 180 SEK/year ≈ 15 SEK/month ex VAT.
- **Free tiers:** email (Brevo, 300/day), monitoring (Healthchecks.io, UptimeRobot) and the data (Bolagsverket/SCB HVD) all cost 0 SEK.
- **Stripe Sweden:** 1.5 % + 1.80 SEK (standard EEA card), 2.8 % + 1.80 SEK (premium or **company card, which is likely for B2B**), plus Stripe Billing 0.7 % for subscriptions. Calculated below with company cards, the conservative case.
- **Not included:** income tax and egenavgifter, your own time, and bookkeeping software (0–200 SEK/month; shown separately).

## VAT: two possible treatments

The customer's net cost is the same either way. A VAT-registered accounting firm deducts any VAT you charge.

**A. VAT exemption (momsbefrielse), turnover ≤ 120,000 SEK/year** (the limit since 1 Jan 2025; it must be applied for at Skatteverket and applies to the whole business, including your other activities):
- Price **249 SEK, no VAT**. Invoices must state that the business is VAT-exempt.
- You cannot deduct input VAT. Purchases from abroad (Hetzner DE, possibly Stripe Billing IE) are assumed to carry 25 % reverse-charge VAT you must pay but cannot deduct. Stripe card fees are treated as VAT-exempt financial services. *Confirm with Skatteverket.*

**B. VAT-registered:** charge 249 + 25 % = 311.25 SEK and pay over 62.25 SEK. Input VAT and reverse charge net to zero. Stripe's percentage fee applies to the full 311.25 SEK.

## Per customer and month (249 SEK list price, company card)

| | A: VAT-exempt | B: VAT-registered |
|---|---|---|
| Charged to customer | 249.00 | 311.25 |
| VAT paid over to Skatteverket | – | −62.25 |
| Stripe card fee (2.8 % + 1.80) | −8.77 | −10.52 |
| Stripe Billing 0.7 % (A: +25 % reverse charge) | −2.18 | −2.18 |
| **Net per customer** | **238.05** | **236.31** |

## Fixed costs per month

| | A | B |
|---|---|---|
| Hosting (78 SEK, A: +25 % non-deductible) | 97.50 | 78.00 |
| Domain (15 SEK, A: +25 %) | 18.75 | 15.00 |
| **Fixed total** | **116.25** | **93.00** |

## Monthly profit before income tax

| Paying customers | A: 249 SEK | B: 249 SEK | A: 199 SEK (founding price) |
|---|---|---|---|
| 3 | 597.90 | 615.93 | 453.42 |
| 4 | 835.95 | 852.24 | 643.31 |
| **5** | **1,074.00** | **1,088.55** | 833.20 |
| 6 | 1,312.05 | 1,324.86 | **1,023.09** |

(At 199 SEK, net per customer under A is 199 − 7.37 − 1.74 = 189.89.)

**Result:** **5 paying customers at 249 SEK** give about 1,075–1,090 SEK/month profit before income tax, with either VAT treatment. At the founding price of 199 SEK it takes **6**. If you use paid bookkeeping software (about 100–200 SEK/month), add **1 customer**.

**Recommendation:** treatment A while turnover stays far below 120,000 SEK/year (1,245 SEK/month is about 15,000 SEK/year). It means no VAT returns, and customers' net cost is unchanged. Choose B if you already run a VAT-registered business, since the exemption covers the whole business.

**Income tax (separate, not included):** for an enskild firma the profit is taxed as business income. Egenavgifter are about 29 % (lower with schablonavdrag) plus municipal tax, so roughly 50–60 % in total depending on your other income. 1,075 SEK of profit is about 450–550 SEK after tax.

## Sources
- Stripe Sweden pricing: https://stripe.com/en-se/pricing
- Hetzner 2026 price changes: https://findstack.com/resources/hetzner-price-increase-2026 · https://wz-it.com/blog/hetzner-preiserhoehung-juni-2026-cpx-ccx-alternativen/ · https://agentdeals.dev/hetzner-pricing-2026
- VAT exemption at 120,000 SEK: https://www.dagensjuridik.se/nyheter/hojd-omsattningsgrans-for-moms/ · https://www.bokio.se/blogg/hojd-omsattningsgrans-for-moms/ · https://ekonomico.se/momsbefrielse-hojd-omsattningsgrans/
