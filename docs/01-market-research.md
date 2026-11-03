# 1. Market research: 10 Swedish micro-business opportunities

Research date: 2026-11-03. Target: **probability of reaching 1,000 SEK/month recurring revenue**, not maximum revenue.

## Method and limits

- Evidence comes from web search results: official pages (Bolagsverket, PTS, SCB, Upphandlingsmyndigheten, TED docs) and competitor/vendor pages. The sandbox couldn't fetch most pages directly, so some figures are search snippets. Each one is labelled **[verified-official]**, **[vendor-stated]** or **[secondary]**.
- "Customers already pay" means a competitor is charging for the same job today. That is evidence that people pay. It is **not** evidence that they will pay *you*. That gets tested in `02-validation-plan.md`.
- Demand is never assumed. Every number marked *assumption* has to be checked.

## Scoring

Each opportunity is scored 1–5 (5 = best for this goal) on:

| Criterion | What 5 means |
|---|---|
| Paid evidence | Several competitors visibly charge for this exact job |
| Competition gap | A cheap, narrow, self-serve option is missing or weak |
| Acquisition ease | Prospects can be listed and contacted directly, for free and legally |
| Maintenance | Few sources, stable official data, little manual support |
| Feasibility | One developer can ship an MVP in about 1–2 weeks |
| Data/legal risk | Open-licensed data, no personal-data processing about private persons |

**P(1k)** is my judgment of the relative probability of reaching 1,000 SEK MRR within about 6 months. It is a ranking device, not a forecast.

---

## The 10 opportunities

### 1. New-company registration feed ("Nya bolag-bevakning") for local B2B sellers
Every week, deliver the newly registered **aktiebolag, handelsbolag and föreningar** in a customer's region to accounting firms, insurance brokers, banks' SME advisors, web agencies, office suppliers and similar sellers. New companies need all of these services.

- **Data:** Bolagsverket made basic company data free from 3 Feb 2025 under the EU high-value datasets regulation, via API and downloadable files. No fee and no agreement required. [verified-official: Bolagsverket "Värdefulla datamängder", press release 2025] The bulk file `bolagsverket_bulkfil.zip` is updated **weekly**. [verified-official: Bolagsverket "Nedladdningsbara filer"] SCB's company register also became free from 26 June 2025 and contains a *reklamspärr* (advertising opt-out) flag. [verified-official: Regeringen press release May 2025; SCB HVD page]
- **People already pay:** Merinfo sells lists of "nyregistrerade företag, de senaste 12 månaderna, per län, kommun och bransch". Adressleverantören sells a "nyregistrerade bolag" register. Marknadsinformation, Bisnode/D&B and others sell selections. List prices run roughly 0.50–15 SEK per address, usually as one-off exports. [vendor-stated, via search]
- **Competition gap:** Incumbents sell broad databases or one-off exports, with prices often hidden behind a quote. I found no published cheap, fixed-price, self-serve *weekly local* subscription. That does not prove none exists; checking is part of validation.
- **Buyer economics** *(assumption to validate)*: Swedish bookkeeping for a small AB costs about 1,500–4,000 SEK/month [secondary: several accounting-firm price pages]. One won client is worth more than ten years of a 249 SEK/month subscription.
- **Acquisition:** You can build the prospect list from the **same dataset**: accounting firms are filterable by SNI 69.20 / business description. Cold B2B email to a company's generic address is a recognised practice in Sweden; the Marketing Act's opt-in rule applies to natural persons. Phone works too.
- **Maintenance:** one official weekly file, one parser, a diff. Very low.
- **Risks:** The file format isn't fully documented to me: it uses `$`-structured fields and a few malformed quotes [secondary]. Many new ABs list a home or c/o address. Sole proprietorships use personnummer, so they're **excluded** to stay out of private-person data. Reuse licence and attribution terms must be confirmed.

Scores: Paid evidence 4 · Gap 3 · Acquisition 5 · Maintenance 5 · Feasibility 5 · Data/legal 4 → **P(1k): High**

### 2. Niche public-procurement alerts (one vertical, e.g. cleaning, painting, translation, IT consulting)
- **People already pay:** Visma Opic/Mercell monitoring has been quoted at about 99–408 SEK/month [secondary, mixed age]. Pabliq starts at 10,900 SEK/year [secondary: tenderrender market map, Oct 2026]. Tendium, Byggfakta Tender and others compete.
- **Data:** TED Search API v3 is free and anonymous [verified-official: docs.ted.europa.eu], but covers above-threshold notices only. Since 2021 all Swedish procurements must be published in *registered advertising databases* [verified-official: Konkurrensverket]. Those are commercial platforms (Mercell, e-Avrop, Kommers Annons, Pabliq…), and no public notice-level API was confirmed [Upphandlingsmyndigheten quality declaration 2026; 2024 study proposes one].
- **Assessment:** Willingness to pay is proven, but the SME-relevant below-threshold data means scraping several commercial sites, with terms-of-service and breakage risk. Competition is crowded and cheap.

Scores: 5 · 2 · 4 · 2 · 3 · 2 → **P(1k): Medium**

### 3. Narrow Fortnox marketplace integration
- **People already pay:** Fortnox lists 400–500+ integrations. Third-party apps typically cost about 300–700 SEK/month (e.g. Aira, 699 SEK/user/month), and customers also pay Fortnox an integration licence [vendor-stated/secondary].
- **Assessment:** Strong distribution if you find an unserved niche. But it needs a partner agreement and app review, OAuth, accounting-correctness liability and support load, and you carry platform risk. Time to first revenue is longer.

Scores: 5 · 2 · 3 · 3 · 3 · 4 → **P(1k): Medium**

### 4. Bankruptcy / notice watch on your customer list ("light kreditbevakning")
- **People already pay:** UC and Creditsafe (expensive). BolagsAPI sells POIT announcements from 249 SEK/month, with plans up to 1,299 [vendor-stated].
- **Data:** Post- och Inrikes Tidningar is free to search on the web, but I found **no official API** [Bolagsverket PoIT page]. You would have to scrape it or resell another provider's data.
- **Assessment:** A cheap competitor already exists at the target price point, and the data dependency is fragile.

Scores: 4 · 1 · 3 · 3 · 4 · 3 → **P(1k): Medium-low**

### 5. Accessibility (tillgänglighetslagen / EAA) monitoring for web agencies
- **Driver:** Lag 2023:254 has applied since 28 June 2025. PTS supervises e-commerce, with 28 supervisory cases since 2025 [verified-official/secondary: PTS, lptt.se].
- **Assessment:** The regulation is real, but automated scanners catch only part of the WCAG criteria, so there is a risk of selling false assurance. Free tools (axe, WAVE, Lighthouse) and Siteimprove/Monsido sit at the top end, and the microenterprise exemption is ambiguous.

Scores: 3 · 2 · 4 · 3 · 4 · 3 → **P(1k): Medium-low**

### 6. Hiring-signal leads from Platsbanken (JobTech) for staffing agencies and B2B sellers
- **Data:** The JobTech JobSearch API is open, needs no key and updates in real time [verified-official: jobtechdev.se].
- **Assessment:** Vainu/Dealfront-type tools sell "hiring signals", but recruiters can browse Platsbanken for free, so the value-add is thin unless you enrich the data.

Scores: 3 · 3 · 4 · 4 · 5 · 5 → **P(1k): Medium**

### 7. Building-permit (bygglov) leads for tradespeople
- **Data:** Bygglov decisions must be announced in PoIT (PBL 9:41 a) [secondary: lagen.nu, municipal notices], but there is no API. A notice gives the *property designation*. Turning that into an owner needs Lantmäteriet data (paid) and private-person processing under GDPR. Byggfakta covers larger projects, priced by quote [vendor].
- **Assessment:** Recent rule changes removed permit requirements for many solar and facade changes [secondary, 2025–2026], so the lead volume is shrinking. Legal and data risk is high.

Scores: 3 · 3 · 3 · 2 · 2 · 1 → **P(1k): Low-medium**

### 8. Competitor price monitoring for small Swedish webshops (productised)
- **People already pay:** yes, internationally (Prisync, Price2Spy).
- **Assessment:** Every client means custom scrapers that break, so maintenance is high. Prisjakt covers much of the consumer-facing need.

Scores: 4 · 2 · 3 · 1 · 3 · 3 → **P(1k): Medium-low**

### 9. Uptime / SSL / domain-expiry monitoring for web agencies
- **Assessment:** People do pay, but free tiers (UptimeRobot, Better Stack, Healthchecks) commoditise the market. There is nothing Sweden-specific to defend.

Scores: 3 · 1 · 3 · 4 · 5 · 5 → **P(1k): Low**

### 10. Electricity spot-price API / alerts
- **Assessment:** Free sources (elprisetjustnu.se) and supplier apps already serve hobbyists. B2B buyers use their energy supplier. Little willingness to pay.

Scores: 1 · 1 · 3 · 4 · 5 · 5 → **P(1k): Low**

---

## Ranking (probability of the first 1,000 SEK/month)

The rank is a judgment, not a sort by raw total. The raw total treats all six criteria as equal. For *first revenue*, **paid evidence × gap × acquisition** matters most, so easy-to-build ideas with no paying gap (spot-price, uptime) drop, and ideas with strong proof of payment (procurement, Fortnox) rise.

| Rank | Opportunity (section) | Paid evidence | Gap | Acquisition | Maint. | Feasible | Data/legal | Raw /30 | P(1k) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | New-company feed for local B2B sellers (§1) | 4 | 3 | 5 | 5 | 5 | 4 | 26 | **High** |
| 2 | Niche procurement alerts, TED-first (§2) | 5 | 2 | 4 | 2 | 3 | 2 | 18 | Medium |
| 3 | Fortnox niche integration (§3) | 5 | 2 | 3 | 3 | 3 | 4 | 20 | Medium |
| 4 | Hiring-signal leads, JobTech (§6) | 3 | 3 | 4 | 4 | 5 | 5 | 24 | Medium |
| 5 | Accessibility monitoring for agencies (§5) | 3 | 2 | 4 | 3 | 4 | 3 | 19 | Medium-low |
| 6 | Bankruptcy/notice watch (§4) | 4 | 1 | 3 | 3 | 4 | 3 | 18 | Medium-low |
| 7 | Price monitoring for webshops (§8) | 4 | 2 | 3 | 1 | 3 | 3 | 16 | Medium-low |
| 8 | Bygglov leads (§7) | 3 | 3 | 3 | 2 | 2 | 1 | 14 | Low-medium |
| 9 | Uptime/SSL monitoring (§9) | 3 | 1 | 3 | 4 | 5 | 5 | 21 | Low |
| 10 | Spot-price API (§10) | 1 | 1 | 3 | 4 | 5 | 5 | 19 | Low |

## Recommendation: #1 New-company feed

Why it wins for *this specific goal*:

1. **The data is free, official, weekly, and contains no private persons** once sole proprietorships are excluded. There is nothing to scrape and only one source to maintain.
2. **Willingness to pay is shown** by several vendors selling the same lists today. The open question is whether buyers prefer a cheap weekly subscription to one-off exports.
3. **Buyer ROI is very large.** One won client covers years of subscription, so 249–399 SEK/month is an easy yes *if* the leads convert at all.
4. **You can find customers with the product itself.** The accounting firms, insurance brokers and web agencies in any region are in the same dataset.
5. **Only 4–5 customers** are needed (see `03-product-and-economics.md`).

Runner-up to test in parallel at near-zero cost: **rank 2, niche procurement alerts**, using TED only, for one vertical. Willingness to pay there is the best-proven of all ten.

**What could kill #1** (each is tested before scaling):
- Buyers say "I already get this from Merinfo/Bisnode" or "letters to new companies don't convert".
- The bulk file lacks usable addresses or registration dates, or its reuse terms forbid the use case.
- Volume per region is too low to feel valuable. Sweden registers tens of thousands of new ABs per year, but the count per municipality per week must be measured.

## Sources
- Bolagsverket – Värdefulla datamängder: https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/vardefulladatamangder.5294.html
- Bolagsverket – API för värdefulla datamängder: https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/vardefulladatamangder/apiforvardefulladatamangder.5513.html
- Bolagsverket – Nedladdningsbara filer: https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/nedladdningsbarafiler.2517.html
- Bolagsverket – Avgiftsfri data (press, 2025): https://bolagsverket.se/apierochoppnadata/nyheterochreleaser/2025/avgiftsfridatanarbolagsverketochscblanserarvardefulladatamangder.5516.html
- Regeringen – SCB:s dataregister blir avgiftsfritt: https://www.regeringen.se/pressmeddelanden/2025/05/scbs-dataregister-blir-avgiftsfritt-och-oppet/
- SCB – Värdefulla datamängder: https://www.scb.se/vara-tjanster/bestall-data-och-statistik/foretagsregistret/vardefulla-datamangder--grundlaggande-foretagsinformation/
- Hugging Face mirror (unofficial weekly snapshots): https://huggingface.co/datasets/krafs/bolagsverket-arkiv
- Merinfo: https://www.merinfo.se/ · Adressleverantören: https://adresser.adressleverantoren.se/ringlistor-foretag/ · Marknadsinformation: https://www.marknadsinformation.se/foretagsregister · Adressfakta prices: https://www.adressfakta.se/kopa-adresser/ · Fastighetskalendern (B2B list legality): https://www.fastighetskalendern.se/resurser-blogg/kopa-adresslista-guide
- Bookkeeping prices: https://hagersten-ekonomi.se/artiklar/vad-kostar-lopande-bokforing/ · https://kronanekonomipartner.se/vad-kostar-bokforing/
- Procurement: https://www.konkurrensverket.se/informationsmaterial/nyhetsarkiv/2020/obligatoriskt-att-annonsera-upphandlingar-i-en-registrerad-annonsdatabas-fran-arsskiftet/ · https://prod.upphandlingsmyndigheten.se/globalassets/dokument/statistik/dokument-2026/kvalitetsdeklaration-annonserade-upphandlingar-2025.pdf · https://docs.ted.europa.eu/api/latest/index.html · https://www.tenderrender.com/en-us/market-map · https://inkopsradet.se/upphandling/vill-se-statlig-upphandlingsportal · https://www.pabliq.se/
- Fortnox: https://www.fortnox.se/produkt/prislista · https://hurbra.se/aira-fortnox-lanseras-2026/ · https://astrid.so/guider/bokforing/bokfora-shopify-fortnox
- BolagsAPI (POIT pricing): https://bolagsapi.se/en/compare · https://bolagsapi.se/en/blog/konkurser-kallelser-poit
- PoIT: https://bolagsverket.se/sjalvservice/etjanster/postochinrikestidningar.1697.html · https://lagen.nu/dom/nja/2020s556
- PTS tillgänglighetslagen: https://pts.se/digital-inkludering/lagen-om-vissa-produkters-och-tjansters-tillganglighet/ · https://pts.se/nyheter-och-pressmeddelanden/pts-inleder-en-tillsyn-av-e-handelstjanster/ · https://www.lptt.se/e-handelsbranschen-granskas-av-pts/
- JobTech: https://jobtechdev.se/en/components/jobsearch
- Byggfakta: https://www.byggfakta.se/marknadsbevakning/smart/prismodell · Solar permit rules: https://byggkoll.byggtjanst.se/artiklar/2025/december/nya-bygglovsregler-beror-installation-av-solceller/
