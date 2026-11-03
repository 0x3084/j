# 9. On your Mac: download the official Bolagsverket file and import it

Time: about 30 minutes the first time, about 5 minutes per week after that. Cost: 0 SEK. You need about 3 GB of free disk space.

Everything runs locally. Nothing is published and nobody is contacted. Commands go in **Terminal** (Program → Verktygsprogram → Terminal), one block at a time.

## A. One-time installation

1. **Developer tools** (git). Skip this if `git --version` already prints a version:
   ```bash
   xcode-select --install
   ```
2. **Python 3.12.** Download the macOS installer from https://www.python.org/downloads/ and run it. Then check:
   ```bash
   python3.12 --version        # should print Python 3.12.x
   ```
3. **Get the project.** The repository is on GitHub (`0x3084/j`). If it's private, sign in when git asks: use a personal access token as the password, or GitHub Desktop.
   ```bash
   cd ~
   git clone https://github.com/0x3084/j.git nyabolag
   cd nyabolag
   git checkout claude/micro-saas-sweden-validation-d09vxm
   ```
4. **Create the environment and run the tests:**
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m pytest -q          # expected: 20 passed
   ```
   Every new Terminal window: `cd ~/nyabolag && source .venv/bin/activate`.

## B. Download the official file (every week, from Tuesday)

Bolagsverket publishes the file Monday night (Last-Modified Monday about 02:00 UTC in the sample).

1. **Confirm the link yourself, the first time:** open
   https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/nedladdningsbarafiler.2517.html,
   right-click **bolagsverket_bulkfil.zip** → *Kopiera länk*. It is expected to be
   `https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip`.
   Use whatever the page shows if it differs.
2. **Read the licence/terms text** on that page (and the dataportal.se entry for Bolagsverket). Save it as a PDF: in Safari, Arkiv → Exportera som PDF, to `~/nyabolag/legal/`.
3. **Check the file date, then download** (about 250 MB):
   ```bash
   export NYABOLAG_DATA_DIR=./data
   export BULKFILE_URL="https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip"
   curl -sI "$BULKFILE_URL" | grep -i -E "last-modified|content-length|content-type"
   python -m nyabolag fetch     # saves data/raw/bulkfil-<today>-<hash>.zip, refuses non-zip responses
   ```
   Note the Last-Modified date. That is the **file date** used below (written FILEDATE, format YYYY-MM-DD).
4. **Look at the real format:**
   ```bash
   F=$(ls -t data/raw/bulkfil-*.zip | head -1); echo $F
   python -m nyabolag inspect "$F" -n 3
   ```
   Expected: a header with 11 columns starting `organisationsidentitet`, then 3 parsed companies. If the header differs, stop and send me the output.

## C. Verify the sample against the official file (first time only)

```bash
python validation/verify_sample.py "$F"
```
Expected: `108/108 sample companies found …`. A few missing can be companies deregistered since 26 Oct; the script says so. **A large number missing means the third-party copy was wrong. Stop and tell me.**

This is the step that turns the sample from "via third-party copy" into **verified official data**.

## D. Import

```bash
python -m nyabolag ingest "$F" --as-of FILEDATE     # about 1 minute for ~3 M rows
python -m nyabolag stats
```
Expected roughly: `rows` about 3,000,000, `new` 6,000–8,000 (registrations in the last 60 days), `shelf_flagged` about 30 % of them, `bad_rows` 0 or a handful. Send me the JSON if anything looks very different.

## E. Reklamspärr verification (after you have API credentials; see doc 13, step 3)

1. Put the credentials in a private file. It is never committed: `.env` is in `.gitignore`.
   ```bash
   cat > .env <<'EOT'
   HVD_CLIENT_ID=paste-client-id
   HVD_CLIENT_SECRET=paste-client-secret
   # Confirm both URLs on Bolagsverket's developer portal / in the e-mail you receive:
   HVD_TOKEN_URL=https://portal.api.bolagsverket.se/oauth2/token
   HVD_API_BASE=https://gw.api.bolagsverket.se/vardefulla-datamangder/v1
   EOT
   chmod 600 .env
   set -a; source .env; set +a
   ```
   The email gives separate credentials for **test** and **production**. Try the test environment first, using the test URLs from the email.
2. Dry run, which makes no API calls:
   ```bash
   AREA="Norrköping,Kolmården,Krokek,Åby,Skärblacka,Svärtinge,Vikbolandet,Kimstad,Norsholm,Östra Husby,Arkösund,Simonstorp,Strömsfors,Linköping,Linghem,Ljungsbro,Malmslätt,Sturefors,Vikingstad,Vreta Kloster,Brokind,Nykil,Ulrika"
   python -m nyabolag verify-reklamsparr --cities "$AREA" --forms AB,HB,KB,EK --snapshots 1 --dry-run
   ```
   Expect roughly 100–250 companies (the 60-day window), about 2–5 minutes.
3. Try 3 lookups, then the rest:
   ```bash
   python -m nyabolag verify-reklamsparr --cities "$AREA" --forms AB,HB,KB,EK --snapshots 1 --limit 3
   python -m nyabolag verify-reklamsparr --cities "$AREA" --forms AB,HB,KB,EK --snapshots 1
   ```
   The result shows `verified`, `blocked` and `failed`. Any `failed` stay **unverified and are never delivered**. If everything fails, the token URL or API base is wrong (check the email or portal). Bolagsverket's limit is 60 calls/minute; the tool stays under it.

## F. Generate the reports

```bash
# Prospect sample (privacy-safe, masked names) – this is what you show accounting firms:
python validation/sample_report.py reports --file-date FILEDATE --contact "Svara på mejlet eller ring 07X-XXX XX XX."
open reports/provrapport-redovisningsbyraer.html
# PDF: in Safari, Arkiv → Exportera som PDF (or ⌘P → Spara som PDF)

# Internal full lists (addresses) – never send these to prospects:
python validation/region_report.py reports-intern --file-date FILEDATE
```

## G. Weekly routine during validation (manual, about 5 minutes)

Run on Tuesday morning:
```bash
cd ~/nyabolag && source .venv/bin/activate && set -a; source .env; set +a
export NYABOLAG_DATA_DIR=./data BULKFILE_URL="…as above…"
python -m nyabolag fetch
F=$(ls -t data/raw/bulkfil-*.zip | head -1)
python -m nyabolag ingest "$F" --as-of FILEDATE
python -m nyabolag verify-reklamsparr --cities "$AREA" --forms AB,HB,KB,EK --snapshots 1
# per paying customer (verified companies only, default):
python -m nyabolag export --cities "Linköping,Linghem,Ljungsbro,Malmslätt,Sturefors,Vikingstad,Vreta Kloster,Brokind,Nykil,Ulrika" --forms AB,HB,KB,EK --snapshots 1 --out "kund-Byrå-AB-$(date +%F).csv"
python -m nyabolag purge --days 365     # data retention
```
Email the CSV to the customer from your normal email account. Time Machine backs up `~/nyabolag/data`. Keep the Mac's disk encryption (FileVault) on.

**Troubleshooting**
- `curl` returns HTML, or the fetch says "not a zip": the link has changed. Copy it again from the page.
- `ModuleNotFoundError`: you forgot `source .venv/bin/activate`.
- `HVD_CLIENT_ID … not set`: run `set -a; source .env; set +a` in the same window.
