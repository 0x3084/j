# 13. Your steps to the first paying customer

Everything below is done **by you, by hand**. Nothing is sent, published or paid automatically.
- **Cost:** 0 SEK, up to the optional VPS at the very end.
- **Your time:** about 6–8 hours of preparation, then about 2–3 hours/week of calls for 3–6 weeks.
- **Approval gates:** steps marked 🔒 are where you spend money, publish something or contact someone. Decide each one consciously.

## Phase 1: Prove the data (week 0, about 2 hours)

**Step 1. Download and verify the official file on your Mac.** Follow doc 09, sections A–D.
✅ Done when `verify_sample.py` prints **108/108** (or a few missing that you've explained) and `ingest` shows `bad_rows` 0.
❌ If many are missing or the format differs, stop and send me the output.

**Step 2. Save the licence/terms text** from Bolagsverket's download page and dataportal.se as PDFs in `~/nyabolag/legal/`.
✅ Done when you've read them and nothing forbids commercial reuse. If anything is unclear, email Bolagsverket and ask: "Får grunddata från värdefulla datamängder vidareförädlas och säljas som tjänst?"

**Step 3. Register for the free API credentials.** On bolagsverket.se, open *API:er och öppna data → Hämta företagsinformation → Värdefulla datamängder → API för värdefulla datamängder → Kundanmälan*. The form asks for an email address and mobile number. The client ID and secret arrive by email and SMS.
- Then follow doc 09 E: `.env`, dry run, 3 test lookups, then the full run.

✅ Done when `verify-reklamsparr` shows `verified` ≈ candidates and `failed` = 0. Until then, `export` correctly returns **0 companies**: nothing unverified can be delivered.

**Step 4. Generate the sale-ready sample** (doc 09 F) for Norrköping and Linköping.
- Open the HTML and check:
  - **no** UTKAST banner;
  - names masked;
  - no org numbers, addresses or postcodes.
- Then export it as a PDF (Safari → Arkiv → Exportera som PDF). Make one PDF per city if you like: run the script and keep only one city's figures in the email.

## Phase 2: Be allowed to sell (week 0, about 2–3 hours)

**Step 5. 🔒 Business setup** (free of charge):
- **No business yet:** apply for **F-skatt** at Skatteverket (verksamt.se → "Starta"). It's free. Registering an enskild firma in Bolagsverket's handelsregister is optional and costs a fee, so skip it.
- **VAT:** on the same application choose **momsbefrielse** (turnover ≤ 120,000 SEK/year), *or* VAT registration if you already have VAT-registered activity (doc 06). Ask Skatteverket for the exact wording to put on invoices.
- **Bookkeeping:** keep a simple ledger from day 1 (a spreadsheet is enough at this scale); save every invoice and receipt.

**Step 6. Write the three legal texts.** Use the templates below and adapt them.
- Keep them as PDFs. Send the **terms** and the **privacy notice** with the first invoice or payment link; there is no website yet.
- The **LIA** stays in your files.

**Step 7. Prepare the call list.**
- Start from doc 07 (the 14 firms in Norrköping/Linköping) and add 15–20 from hitta.se or eniro.se.
- For each firm, look up its **company form**. Sole traders get **phone/letter only**.
- Make the tracking sheet (doc 10).

**Step 8. 🔒 Choose how customers pay** (no money involved yet):
- **Recommended for customers 1–5: an invoice per quarter in advance (747 SEK)** from a simple template.
  - It must include: your name and personnummer/org.nr, "Godkänd för F-skatt", the invoice number and date, the customer's name and address, the description, the amount, and the VAT line ("momsbefriad" text or 25 % VAT). Payment by Swish/bank giro/bank transfer.
  - No Stripe needed.
- **Alternative:** activate Stripe and create **one Payment Link** (249 SEK/month). Do this only when the first customer says yes.

## Phase 3: Sell (weeks 1–6)

**Step 9. 🔒 Approve and start calling.**
- **Week 1:** call the 7 A-prospects with the scripts in doc 11. Call Tuesday to Thursday, 9–11 or 13–15.
- Say who you are, and honour "no" immediately (write "do-not-contact").

**Step 10. 🔒 Send the sample** within an hour of each "ja, skicka":
- **When the firm is an AB:** email from your normal mailbox, using the doc 11 text plus the PDF.
- **Otherwise:** only when the person on the phone asked for it.

**Step 11. Follow up after 2–3 working days** with the follow-up script. Offer next Monday's **real** list as a free trial week:
```bash
python -m nyabolag export --cities "<their towns>" --forms AB,HB,KB,EK --snapshots 1 --out "prov-<byrå>-$(date +%F).csv"
```
The export contains verified companies only. Attach the customer terms.

**Step 12. 🔒 Ask for payment** after the trial week (doc 11 script). When they say yes: send the invoice or Payment Link with the terms and privacy notice.
- **🎉 First paying customer** = an invoice paid, or a successful Payment Link charge.

**Step 13. Deliver every week** (doc 09 G, about 5 minutes) and log it. Once a month, ask: "Har ni fått någon kund via listan?"

**Step 14. 🔒 When ≥ 3 customers pay:** we move the weekly job to a small VPS (about 80 SEK/month, doc 06).
- Test Bolagsverket access from that VPS first (audit R7).
- Fix the open items S5–S7 and D8 in doc 12 before any public web page or self-service checkout.

---

## Appendix A: Integritetspolicy (template)
> **Integritetspolicy för Veckans Nya Bolag** (drivs av [namn], [org.nr/personnummer], [ort], [e-post])
>
> **Vilka uppgifter vi behandlar.** Vi behandlar uppgifter om nyregistrerade juridiska personer (aktiebolag, handelsbolag, kommanditbolag, ekonomiska föreningar) från Bolagsverkets och SCB:s öppna register: namn, organisationsnummer, registreringsdatum, bolagsform, postadress och verksamhetsbeskrivning. Ibland innehåller ett bolagsnamn eller en adress uppgifter som kan kopplas till en person, och då är de personuppgifter. Vi behandlar inga uppgifter om enskilda firmor, styrelseledamöter, c/o-namn, e-postadresser eller telefonnummer till bolagen.
>
> **Ändamål och rättslig grund.** Vi sammanställer listor åt företag som erbjuder tjänster till nystartade bolag. Rättslig grund är berättigat intresse (art. 6.1 f GDPR). Vi har gjort en intresseavvägning.
>
> **Mottagare.** Våra prenumeranter, som är företag. De ansvarar själva för hur de använder uppgifterna i sin marknadsföring.
>
> **Reklamspärr och invändningar.** Bolag med reklamspärr hos SCB tas aldrig med. Du kan när som helst invända mot att ett bolag förekommer i våra listor. Mejla [e-post] med organisationsnumret, så tar vi bort bolaget från alla framtida listor.
>
> **Lagring.** Levererade listor sparas i högst 12 månader.
>
> **Dina rättigheter.** Du har rätt till information, rättelse, radering och att invända. Du kan klaga hos Integritetsskyddsmyndigheten (imy.se).
>
> **Kunduppgifter.** För våra kunder sparar vi kontaktuppgifter och fakturor (avtal och bokföringslagen, 7 år).

## Appendix B: Kundvillkor (template, short)
> 1. **Tjänsten.** Veckovis lista (CSV/Excel) med nyregistrerade bolag i kundens valda område, från Bolagsverkets och SCB:s öppna data. Vi garanterar inte att listan är fullständig eller felfri.
> 2. **Pris och betalning.** 249 kr/mån [momsbefriad / exkl. moms], faktureras kvartalsvis i förskott eller dras månadsvis med kort. Ingen bindningstid. Uppsägning gäller från nästa period.
> 3. **Användning.** Kunden använder listan i sin egen verksamhet. Det är inte tillåtet att sälja den vidare eller publicera den.
> 4. **Marknadsföring.** Kunden följer marknadsföringslagen och GDPR. Varje utskick ska visa vem avsändaren är och hur mottagaren slipper fler utskick. Kunden respekterar invändningar och kontaktar inte bolag som har bett om att slippa. Listan innehåller inga e-postadresser, och kunden får inte skaffa dem för att skicka oönskad e-post till fysiska personer.
> 5. **Ansvar.** Vårt ansvar är begränsat till avgiften för de senaste tre månaderna.
> 6. **Personuppgifter.** Se integritetspolicyn. Kunden är självständigt personuppgiftsansvarig för sin egen användning av listan.

## Appendix C: Intresseavvägning (LIA), one page, keep internally
**Interest:**
- Ours: to sell a B2B data service.
- Our customers': to offer services to new companies.
- Society's: reuse of public register data, which the EU HVD regulation is designed to enable.

**Necessity:** only the fields needed to make contact by post or a visit. No enrichment, no people, no sole traders.

**Balancing:**
- The data concerns business activity and is already public.
- New company owners can reasonably expect B2B offers.
- Reklamspärr is respected, objections are honoured permanently, and retention is 12 months.
- Prospect samples are masked.

**Conclusion:** our legitimate interest outweighs the intrusion. Review yearly, or if the data or use changes.
