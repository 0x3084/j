# 4. Real-data validation (2026-11-03)

## Bottom line

| Question | Answer | Confidence |
|---|---|---|
| Did we run on real Bolagsverket data? | **Yes**: 9,117 real rows from the official weekly file of 2026-10-26 | High that they are real; **not yet verified first-hand** (see "Provenance") |
| Does the parser handle the real format? | Yes, after 6 fixes (below). 0 malformed rows | High |
| Are "new" records really new registrations? | Yes, when decided by `registreringsdatum`. 300/300 matched the official API. **But 30 % are shelf companies**, now filtered out | High |
| Volume in the pilot region | Norrköping 53, Linköping 53, Finspång 2 over 4.7 weeks ⇒ **≈ 11/week each for Norrköping and Linköping, ≈ 0.4/week for Finspång** | High (for that period) |
| Licence for commercial reuse | Free, no agreement (Bolagsverket). SCB: free use and redistribution with attribution, and redistributors must inform about reklamspärr. The exact licence name is unconfirmed (CC BY 4.0 vs CC0) | Medium |
| Reklamspärr | Implemented as **exclusion**. Status is known for only 3/108 sample companies. The rest need a free API lookup before launch | High |

## Provenance: what is and isn't verified

**This environment's network policy blocks** `bolagsverket.se`, `vardefulla-datamangder.bolagsverket.se`, `www.scb.se` and `huggingface.co` (HTTP 000, DNS denied). Only GitHub and package registries are reachable. The official file could therefore not be downloaded here.

What was used instead: the public GitHub project `pingyan-data/sweden-new-companies`. It downloads the official file every week (from `https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip`) and commits the **untouched rows** of each week's new registrations and deregistrations, plus:
- metadata for the 2026-10-26 file: Last-Modified `Mon, 26 Oct 2026 02:23:12 GMT`, 251.4 MB, sha256 `fe19f31d…2813`;
- 300 raw responses from Bolagsverket's official *API för värdefulla datamängder* for companies registered 2026-09-21.

Consistency checks I ran on that copy:

| Check | Result |
|---|---|
| Rows parse in the documented official format (11 columns, `$`/`|` structure, `-ORGFO`/`-IDORG` codes) | 9,117/9,117 rows, 0 bad rows |
| Bulk row vs official API response, **registration date** | **300/300 identical** |
| Bulk row vs API, name/postcode/town | 298/300 identical. The 2 differences are shelf companies renamed and moved between file date and API lookup, which is expected |
| Org numbers | Sequential 559602…–559608… for 2026-09-21 → 10-23, as expected for new AB numbers |
| Independent web search for 5 sample companies | Not yet indexed anywhere (normal for companies under 6 weeks old). This neither confirms nor refutes |

**Conclusion:** the rows are real register data, with very high likelihood. But this is not "downloaded from Bolagsverket by me", and the report is marked UTKAST (draft) until it is regenerated from the official download. That takes about 10 minutes once the hosts are allowed (see "What remains").

## Parser incompatibilities found and fixed

| # | Assumed before | Real format | Fix |
|---|---|---|---|
| 1 | Form code `AB` | `AB-ORGFO` | Strip the type suffix |
| 2 | Address with postcode before town | `street$c/o$TOWN$POSTCODE$SE-LAND` | Positional parse (fallback kept) |
| 3 | 10 columns | 11: extra `pagandeAvvecklingsEllerOmstruktureringsforfarande` | Rows with ongoing liquidation, bankruptcy or reconstruction are skipped |
| 4 | Whole file read into memory | ~1 GB unpacked, ~3 M rows | Streaming reader: 500k rows in 5 s at 26 MB RAM |
| 5 | Plain CSV | Line breaks in descriptions, backslash-escaped quotes in a few rows | Real CSV parser with `escapechar`, whitespace normalised |
| 6 | Several names: take the first | `Name$FORETAGSNAMN-ORGNAM$date\|Alt$SARS_…` | Pick the item typed `FORETAGSNAMN` |

## Are detected records really newly registered companies?

The real file contains **the full history of the register** (about 3M rows, mostly deregistered). That changed the detection design:
- **Before:** "new = org number not in the previous snapshot". That catches late-appearing, corrected or reinstated records too, and needs a baseline week.
- **Now:** "new = never seen before **and** `registreringsdatum` within 60 days of the file date". Old companies that reappear are never "new" (covered by a test). The first import already finds recent registrations, so no baseline week is needed.
- **Verification:** for all 300 companies looked up in the official API, `organisationsdatum.registreringsdatum` equals the bulk file's date. The API also shows SCB received them 4 days later (`infortHosScb`).
- **Lag:** the file of Monday 2026-10-26 contained registrations up to Friday 2026-10-23.

**Shelf companies (lagerbolag)** are genuine registrations but useless as leads. Formation agents register them in bulk at their own address and sell and rename them later.

| Agent address | Registrations in 4.7 weeks | Name pattern |
|---|---|---|
| BOX 427, 351 06 Växjö | 821 | Grundbulten 163151 AB … |
| BOX 12086, 402 41 Göteborg | 441 | Startplattan … Aktiebolag |
| BOX 270, 851 04 Sundsvall | 189 | Goldcup / Fundamentet … |
| BOX 292, 791 27 Falun | 176 | Aktiebolaget Grundstenen … |
| 10 more agents | 428 | Startgropen, Wint Startup, Lagerbolaget C, NorrGuldet, Calico nr, Aktieboken … |

In total, **2,055 of 6,857 (30 %)** are flagged and never delivered. The rule is: a numbered name whose stem recurs at least 3 times, or 10 or more registrations at one address. I checked all flagged addresses by hand and found no false positives. None were in the pilot region.

*Missed opportunity, not built:* when a shelf company is sold, renamed and moved into a customer's area, that's effectively a new business. Detecting it needs two consecutive snapshots.

## Sample report: Norrköping, Linköping, Finspång

The generator is `validation/region_report.py`. Municipalities are matched by postal town, which approximates municipal borders. It includes legal persons only (AB, HB, KB, ek. för.), with no shelf companies and nothing deregistered, in liquidation or with reklamspärr.

| Municipality | New companies 2026-09-21 – 10-23 | Per week |
|---|---|---|
| Norrköping | 53 | ≈ 11 |
| Linköping | 53 | ≈ 11 |
| Finspång | 2 | ≈ 0.4 |

The 108 companies: 104 AB and 4 HB. About 15 are holding-type companies ("äga och förvalta aktier"), which are still bookkeeping and annual-report clients. 6 are registered at an apartment address (`lgh`), i.e. the owner's home. Business-description keywords: konsult 44, fastighet 13, handel 10, bygg 8, el 7, IT 6.

**Implications for the offer:**
- **Finspång** cannot be sold alone (about 2 a month). Sell an *Östergötland / Norrköping + Finspång* area instead.
- **Volume:** about 11 per week in a city is enough for a weekly list, which passes the Phase 0 criterion (≥ 10/week) for Norrköping and Linköping individually.

Outputs are not committed, because they contain real company data:
- `provrapport-kund.html`: for prospects, with **no street addresses**.
- `provrapport-intern.html` and `nya-bolag-<kommun>.csv`: the internal versions with addresses, i.e. the actual subscription format.

## Licence and reuse conditions

- **Bolagsverket** (official pages, via search): the downloadable files and the HVD API are free, "Det kostar ingenting och det krävs inga avtal". The legal basis is EU Implementing Regulation 2023/138 (high-value datasets), which requires reuse with no restrictions beyond, at most, attribution. I found **no named licence** on the pages I could see. A third-party mirror labels the files CC BY 4.0. → *Action: read the licence text on the "Nedladdningsbara filer" page or dataportal.se entry and save a copy.* Until then, attribute as "Källa: Bolagsverket".
- **SCB** company register (free since 26 June 2025): according to a third party who read SCB's user terms in Registreringsportalen on 2026-10-10, the data may be used and redistributed with no limits other than attribution ("SCB" / "Statistiska centralbyrån", plus "egen bearbetning" when processed). Also "Vid vidarespridning av uppgifter svarar Användaren för att informera om reklamspärrar". The terms are only visible after a BankID login. SCB's general open data uses CC0. → *Action: log in, read and archive the terms yourself.*
- **Bolagsverket's paid API** for company information (separate from HVD) forbids resale. This product uses only the free HVD data.

## Reklamspärr

- **Where it exists:**
  - Bolagsverket's HVD API returns `reklamsparr` (source SCB) for every company. It was `null` for all 300 real responses. SCB only receives a new company about 4 days after registration, so a brand-new company has rarely had time to register an opt-out.
  - SCB's own API has `reklamSparrTyp` (1 = accepts advertising, 2 = has opted out of post, email and phone advertising), plus separate phone and email blocks.
- **The bulk file itself has no reklamspärr field.**
- **Implemented:**
  - `nyabolag import-reklamsparr <saved responses>` reads both API formats. Any opt-out wins, and unknown non-null values count as an opt-out.
  - Companies with an opt-out are **excluded** from every delivery. That is stricter than SCB's minimum (inform), because the product exists for direct marketing.
  - With `REQUIRE_REKLAMSPARR_CHECK=1` (the default), paying customers only receive companies whose status was actually checked. The CSV column shows "Nej (kontrollerad YYYY-MM-DD)" or "Ej kontrollerad".
  - The same table can hold manual objections (source `objection`). The GDPR right to object to direct marketing is absolute.
- **Not built (needs credentials only you can create):** an automatic weekly lookup of each new company in the HVD API, using OAuth client credentials from Bolagsverket's free registration form, at about 25 lookups/week for the region (limit 60/min). Until then, only 3/108 sample companies have a checked status.

## What remains before the data side is launch-ready
1. **Allow network access** in the environment settings to `vardefulla-datamangder.bolagsverket.se`, `bolagsverket.se` and `www.scb.se`, or run on your own machine or VPS. Then:
   ```bash
   BULKFILE_URL=https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip python -m nyabolag fetch
   python -m nyabolag inspect data/raw/bulkfil-*.zip
   python -m nyabolag ingest data/raw/bulkfil-*.zip --as-of <Last-Modified date>
   python validation/region_report.py out/ --file-date <date>
   ```
   Check that the 108 sample org numbers appear in the official file with the same registration dates. That makes the sample first-hand verified, and the UTKAST note can be removed.
2. **Register** (you) for HVD API credentials. Then add the small weekly lookup step for reklamspärr (and SNI codes, which come in the same response).
3. **Archive** the licence and terms texts from Bolagsverket and SCB.
