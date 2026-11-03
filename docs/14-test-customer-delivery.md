# 14. Test-customer delivery (2026-11-03)

**Test customer:** nathanhabarugira@outlook.com. Area: Norrköping och Linköping (23 postal towns). Forms: AB, HB, KB, EK. Price: 249 kr/mån.
- **No payment:** manual billing record, no Stripe, nothing charged.
- **Not public:** no web server deployed.

## What ran (`validation/test_customer_run.py`, TEST MODE)
| Step | Result |
|---|---|
| Fictional bulk file in Bolagsverket's real format | 17 fictional companies plus 1 fictional sole trader. Org numbers deliberately **fail the Luhn check**, so they can never be real companies; names start with "DEMO" |
| Ingest | 17 new, 3 shelf companies flagged, sole trader dropped, 0 bad rows |
| Reklamspärr | Checked against a **local DEMO stub**, not Bolagsverket. Labelled "DEMO – fiktiv kontroll" in the file. 1 opted-out demo company correctly excluded |
| Area filter | Demo company in Stockholm excluded |
| Test customer | Created (status active, manual billing, no charge) |
| Welcome email | Written to outbox: `[TEST] Välkommen till Veckans Nya Bolag` |
| Weekly delivery | `[TEST] Nya bolag v. 45: 12 st i Norrköping och Linköping`, with `.xlsx` and `.csv` attached |
| Automatic checks | Recipient, `[TEST]` subject, test banner in both text and HTML, no links to non-existent pages, xlsx opens and every cell is stored as text, CSV parses, only DEMO companies, reklamspärr label correct: **all passed** |
| iPhone rendering (390 px) | No horizontal scroll in either email |

**Why no real companies were used:** no real company has yet passed *our* reklamspärr verification. The 3 earlier statuses came from a third party's API lookups, and the data itself still awaits first-hand verification (doc 09 C). Real data appears only after doc 13 steps 1–3.

**Safety:** in TEST MODE, mail can only go to addresses listed in `TEST_RECIPIENTS`. Any other customer is skipped before anything is written or sent (tests cover this).

## Why nothing was sent
1. **No email service is configured.** `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_FROM` are not set anywhere.
2. **This cloud session cannot reach SMTP servers.** Outbound connections to smtp.office365.com, smtp-mail.outlook.com and smtp-relay.brevo.com are blocked by its network policy.

So sending has to happen from your Mac, after you choose an email service.

## To send ONE real test delivery (on your Mac, your decision)
1. **🔒 Choose a sending account.** Options:
   - **a)** an SMTP relay with your own domain (e.g. a free tier at an EU provider). This needs an account and DNS records (SPF/DKIM) so mail doesn't land in spam. Best for real customers.
   - **b)** your own mailbox's SMTP with an *app password*. Note: Microsoft is phasing out password-based SMTP for Outlook.com, so it may not work there; Gmail app passwords do.
2. Put the settings in `~/nyabolag/.env`. Never paste them in chat.
   ```
   SMTP_HOST=…
   SMTP_PORT=587
   SMTP_USER=…
   SMTP_PASSWORD=…
   MAIL_FROM=Veckans Nya Bolag <din-adress@din-doman.se>
   REPLY_TO=din-adress@din-doman.se
   VAT_TEXT=moms tillkommer inte (momsbefriad)      # or: exkl. moms
   ```
3. Run the test, which can only reach the allow-listed address:
   ```bash
   cd ~/nyabolag && source .venv/bin/activate && set -a; source .env; set +a
   NYABOLAG_TEST_MODE=1 TEST_RECIPIENTS=nathanhabarugira@outlook.com NYABOLAG_DATA_DIR=./data-test \
     python validation/test_customer_run.py nathanhabarugira@outlook.com
   ```
   This sends exactly two emails (welcome + weekly) to that address. Check spam if they don't arrive within 5 minutes.

## Customer-perspective findings to fix before real customers
- **Placeholders:** the sender address and the VAT text (`VAT_TEXT`).
- **Footer:** should name the seller (name, org.nr/F-skatt) and say where the terms are.
- **Attachments:** both `.xlsx` and `.csv` are attached. Consider dropping the CSV for customers who don't ask for it (simpler on iPhone).
- **Weekly list:** at about 22 companies/week the list in the email body is long but readable on a phone. The Excel file is the working copy.
