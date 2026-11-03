"""Rebuild a bulk-file-shaped zip from third-party JSONL copies of real Bolagsverket rows.

Used because this development environment could not reach vardefulla-datamangder.bolagsverket.se.
Source: github.com/pingyan-data/sweden-new-companies, data/raw/bulk/<date>_bolagsverket_raw.jsonl.
Each line holds {"raw": {<column>: <untouched field string>}} for one register row. Rows are
written back in the official column order, every field quoted, ';'-separated, UTF-8.

This does NOT replace verification against the official file: see docs/04-real-data-validation.md.

usage: python validation/rebuild_bulk_from_jsonl.py <raw.jsonl> <out.zip>
"""
import csv
import io
import json
import sys
import zipfile

COLUMNS = [
    "organisationsidentitet", "namnskyddslopnummer", "registreringsland", "organisationsnamn",
    "organisationsform", "avregistreringsdatum", "avregistreringsorsak",
    "pagandeAvvecklingsEllerOmstruktureringsforfarande", "registreringsdatum",
    "verksamhetsbeskrivning", "postadress",
]


def main(src: str, out: str) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(COLUMNS)
    n = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)["raw"]
            missing = set(COLUMNS) - raw.keys()
            if missing:
                raise SystemExit(f"row lacks columns {missing}")
            w.writerow([raw[c] for c in COLUMNS])
            n += 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bolagsverket_bulkfil.txt", buf.getvalue())
    print(f"wrote {n} rows to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
