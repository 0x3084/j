# 5. GDPR and Swedish direct-marketing review

*This is a practical review, not legal advice. Sources are listed at the end. Before launch, have a one-off review done (for example via Företagarna's legal advice, or an hour with a lawyer). Budget about 0–2,000 SEK.*

## 1. Is there personal data in the product?

| Data | Personal data? | What we do |
|---|---|---|
| Sole traders (enskild näringsidkare, identified by personnummer) | **Yes** | **Never read in.** The parser drops personnummer identities and form EF |
| Company name of an AB/HB | Usually no. **But** names like "Karl Schenström Consulting AB" or "Pierre Aminoff Konsult AB" identify the owner | Kept: it is the core of the product and public register data. Treated as *possibly personal* |
| c/o line (e.g. "C/o Abdullah …") | **Yes**: a private person's name | **Not stored and not exported** |
| Street address | Often the owner's home for one-person ABs (6 of 108 sample rows contain "lgh") | Kept in the paid CSV (needed for letters). **Removed** from the prospect sample |
| Board members, signatories, personnummer | Yes | Not in the file and not collected |
| Customers' contact details (email, name) | Yes | Contract basis (art. 6.1 b). Stored in SQLite on an EU VPS. Stripe handles card data |

So GDPR applies to part of the data. That means a lawful basis, minimisation, transparency and a working objection route.

## 2. Lawful basis: legitimate interest (art. 6.1 f)

Write and keep a short **legitimate interest assessment (LIA)**:
- **Interest:** B2B marketing to new companies, which also need these services. Public register data, published by law for exactly this kind of reuse (EU HVD regulation).
- **Necessity:** only name, org number, form, registration date, business description and postal address. No enrichment with phone numbers, email or people.
- **Balancing:** the data concerns business activity, not private life. Recipients can object at any time. The reklamspärr flag is respected. Expectation: a new company owner expects B2B offers (new ABs routinely get them).

## 3. Transparency (art. 14)

- Publish a privacy notice on the website covering: the source (Bolagsverket/SCB), purpose, recipients (subscribing businesses), retention, the right to object, and contact details.
- Art. 14.5 (b) (disproportionate effort) can cover not notifying each company individually. Customers who send letters must identify themselves and point to how to object. Put this in the customer terms.

## 4. The right to object (art. 21.2–3): absolute for direct marketing

- An objection must stop **all** future deliveries about that company.
- Implemented: add the org number to the `reklamsparr` table with `blocked=1, source='objection'`, and it is excluded everywhere. (For now this is done with one SQL line. It belongs in the admin routine.)

## 5. SCB reklamspärr

- A company can register with SCB that it doesn't want advertising by post, email or phone. SCB's terms require redistributors to *inform* about the flag.
- **We exclude these companies.** Customers using the lists for direct marketing should not be able to receive them.

## 6. Retention

- Company rows: keep only what's needed for diffing. Delivered CSVs: 12 months, then delete. Customers' data: for the contract period plus the bookkeeping law's 7 years for invoices, held in Stripe and the accounting system.

## 7. Marketing law for OUR outreach to prospects (accounting firms)

- **Email to a legal person (AB, HB):** the opt-in requirement in marknadsföringslagen 19 § applies to *natural persons*. Unsolicited B2B email to an AB is allowed.
- **Email to a sole trader:** a sole trader is a natural person, so **opt-in is required**. Use phone or a letter instead. Check each prospect's company form first (column in `07-prospects.md`).
- **Always:** identify yourself and provide a valid opt-out address. This applies to legal persons too.
- **Named employee addresses** (fornamn@byra.se) are personal data, but a work address in a work role is normally covered by legitimate interest. Prefer generic addresses (info@, kontakt@, ort@).
- **Phone:** NIX covers consumers only. For businesses, check SCB's phone block when you have API access. Keep a "don't contact" list and honour it immediately.
- **No automated sending.** Every contact in the validation phase is made manually by you.

## 8. Requirements to pass on to customers (terms of service)

- The customer is an independent controller for its own marketing. It must:
  - follow marknadsföringslagen and GDPR;
  - honour objections;
  - **not send email to the companies without a lawful basis** (we supply no email addresses);
  - include sender identity and an opt-out in every contact.
- The customer may not resell or republish the lists.

## Checklist before the first paying customer
- [ ] LIA written (1 page)
- [ ] Privacy notice on the website; terms of service with the clauses in §8
- [ ] Objection routine tested (org number in, excluded from the next delivery)
- [ ] Reklamspärr lookup running for every delivered company (see doc 04)
- [ ] Attribution text in every delivery ("Källa: Bolagsverket och SCB, värdefulla datamängder, egen bearbetning")

## Sources
- marknadsföringslagen 19–20 §§: https://lagen.nu/2008:486 · https://lawline.se/answers/skicka-e-post-i-marknadsforingssyfte · https://www.delphi.se/uploads/2018/07/09marknadsforing-med-hjalp-av-elektroniska-meddelanden-ny-juridik-nr-3-09-thomson-reutershenrik-bengtsson.pdf
- IMY on the right to object: https://www.imy.se/privatperson/dataskydd/dina-rattigheter/att-gora-invandningar
- B2B lists and legitimate interest: https://www.fastighetskalendern.se/resurser-blogg/kopa-adresslista-guide
- SCB reklamspärr: https://www.scb.se/vara-tjanster/bestall-data-och-statistik/foretagsregistret/kontakta-foretagsregistret/ · https://www.privataaffarer.se/alla-nyheter/nyheter/sa-slipper-du-och-ditt-foretag-forsaljare/
- SCB terms as quoted 2026-10-10 by a third party: https://github.com/nimapima1/horos (OVERLAMNING-hyresgaster.md)
