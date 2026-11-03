# 2. Customer validation plan (run this before any substantial development)

**Hypothesis:** Local B2B service firms will pay about 249 SEK/month (ex. moms) for an automatic weekly list of newly registered companies in their area. Starting with **accounting firms** (redovisningsbyråer), then insurance brokers and web agencies.

**Gate:** Deploy the paid web app only after **≥ 3 businesses have actually paid** (not "said they would"). Until then, everything runs from the CLI, with a Stripe Payment Link and manual emails.

Total time: about 3 weeks of part-time work. Cash cost: about 0–150 SEK (a domain, optional).

---

## Phase 0: Data feasibility (days 1–3). Kill if it fails.

| Check | How | Pass criterion |
|---|---|---|
| File format | Download `bolagsverket_bulkfil.zip` and run `nyabolag inspect <file>` | Org number, name, form, registration date and postal address all parse for >95 % of rows |
| Weekly volume | Diff two consecutive weekly files (wait one week, or use two snapshots from the unofficial HF mirror) with `nyabolag ingest` ×2, then `nyabolag stats` | **≥ 10 new AB/week** in the chosen pilot region (e.g. a län or a large kommun) |
| Address usefulness | Look at 50 new rows by hand | ≥ 70 % have a usable postal address (c/o counts as usable) |
| Licence / reuse | Read the terms on Bolagsverket's HVD page and the file documentation. Email Bolagsverket if unclear | Commercial reuse allowed (the HVD regulation normally requires an open licence such as CC BY 4.0 – **verify**) |
| Advertising opt-out | Check whether the SCB HVD file (free since June 2025) carries *reklamspärr* and can be joined on org number | Joinable. If yes, exclude flagged companies by default |

**Kill / pivot:** if volume is too low or reuse is prohibited, go to the runner-up (rank 2, niche procurement alerts from TED).

## Phase 1: Competitor reality check (week 1, about 2 hours)

As a prospective buyer, request quotes from **Merinfo, Adressleverantören, Marknadsinformation, Bisnode/D&B and Vainu** for: *"nyregistrerade aktiebolag i [region], levererat löpande varje vecka, med postadress"*.

Record the price, minimum order, format and how often it's delivered. If someone already offers a ≤ 300 SEK/month self-serve weekly subscription, the gap is smaller. Then compete on *focus* (one region, clean CSV, opt-out respected) or narrow further, e.g. "new companies in your SNI niche".

## Phase 2: Problem interviews (weeks 1–2)

**Who:** 20–25 businesses in one pilot region: 15 redovisningsbyråer, 5 insurance brokers, 5 web agencies. Pull them from the dataset itself, or from Google Maps / allabolag. Phone calls work better than email for small Swedish firms.

**Goal:** learn, not pitch. Don't mention your product until the last question.

Interview script (Swedish):
1. Hur får ni nya kunder idag? Vilken kanal ger mest?
2. Är nystartade bolag en målgrupp för er? Varför / varför inte?
3. Har ni någon gång köpt adresslistor eller leads? Från vem, vad kostade det, hur gick det?
4. Hur gör ni idag för att hitta nyregistrerade bolag i ert område?
5. Om ni fick en lista varje måndag med alla nya aktiebolag i [kommun], vad skulle ni göra med den? Vem skulle jobba med den?
6. Vad skulle få er att sluta använda en sådan lista?
7. (Last) Jag bygger en sådan tjänst. Får jag skicka förra veckans lista för [kommun] gratis, så ni kan se om den är användbar?

**Record per interview:** segment, current lead sources, money already spent on lists (the strongest signal), and whether they accepted the free sample.

**Pass signal:** at least 6 of 20 already target new companies *or* have bought lists before.

## Phase 3: Concierge pre-sale (weeks 2–3). This is the real test.

1. Generate last week's list for each interested firm's area manually (`nyabolag export --postcodes 41,42 --since-days 7`) and email it as CSV.
2. One week later, ask: *"Ville du ha nästa veckas lista? Det kostar 249 kr/mån exkl. moms, ingen bindningstid. Grundarpris 199 kr/mån för de 5 första som går med."*
3. Payment goes through a **Stripe Payment Link** (no app needed). Deliver manually via the CLI for the first weeks.

| Outcome after about 40 contacts and about 20 conversations | Decision |
|---|---|
| ≥ 3 paid | **Go:** deploy the web app (billing webhooks, dashboard, automatic delivery) |
| 1–2 paid | Iterate on segment, price or list content (e.g. add SNI filter or email-finding) for 2 more weeks |
| 0 paid | **Stop.** Write down why, and test rank 2 with the same playbook |

## Outreach rules (legal and ethical)

- Contact **businesses at their business addresses** only. The Marketing Act's opt-in requirement for email covers natural persons. Prefer generic addresses (info@, kontakt@). Named-employee addresses are personal data, so a GDPR legitimate-interest note applies.
- Every email identifies the sender (name, org number when available) and has a one-line opt-out you honour immediately.
- No invented scarcity or false claims. Never say "guaranteed new clients".
- The product itself lists only legal persons (AB, HB, KB, ek. för.). Sole proprietorships (personnummer) are excluded by design.

Cold email template (Swedish):

> Ämne: Nya aktiebolag i [kommun] förra veckan ([N] st)
>
> Hej,
> Varje vecka registreras omkring [N] nya aktiebolag i [kommun]. Många behöver redovisning från dag ett.
> Jag sammanställer listan automatiskt från Bolagsverkets öppna data (namn, adress, verksamhet). Vill ni ha förra veckans lista gratis som Excel-fil?
>
> /[Namn], [företag], [telefon]
> Vill du inte få fler mejl? Svara "nej tack" så hör jag inte av mig igen.

## Metrics to track (a simple spreadsheet is enough)

Contacted → replied → interviewed → accepted sample → paid. Also note the stated reason for every "no", plus the weekly new-company count per pilot region.
