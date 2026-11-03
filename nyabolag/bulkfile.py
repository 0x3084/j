"""Parser for Bolagsverket's free weekly bulk file (bolagsverket_bulkfil.zip).

Format, checked against real rows from the 2026-10-26 file (see docs/04-real-data-validation.md):
  * zip with one .txt file (~250 MB zipped, ~1 GB unpacked, ~3 M rows), updated weekly
    (published Monday night). Contains the FULL history; most rows are deregistered.
  * ';'-separated, every field quoted, UTF-8, header row with 11 columns:
      organisationsidentitet;namnskyddslopnummer;registreringsland;organisationsnamn;
      organisationsform;avregistreringsdatum;avregistreringsorsak;
      pagandeAvvecklingsEllerOmstruktureringsforfarande;registreringsdatum;
      verksamhetsbeskrivning;postadress
  * structured values: '$' separates parts, '|' separates list items, codes carry a
    type suffix:  "5596028927$ORGNR-IDORG", "AB-ORGFO", "SE-LAND",
    organisationsnamn = "Name$FORETAGSNAMN-ORGNAM$2026-09-21|Other$...",
    postadress = "street$c/o$CITY$POSTNR$SE-LAND"
  * descriptions contain line breaks (use a real CSV parser) and a few rows contain
    backslash-escaped quotes.
Columns are located by header name (COLUMN_ALIASES) so a renamed column fails loudly.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

csv.field_size_limit(sys.maxsize)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "identity": ("organisationsidentitet", "organisationsnummer", "orgnr", "identitetsbeteckning"),
    "name": ("organisationsnamn", "namn", "foretagsnamn"),
    "form": ("organisationsform", "juridisk_form", "juridiskform"),
    "reg_date": ("registreringsdatum", "registreringsdatum_organisation"),
    "dereg_date": ("avregistreringsdatum",),
    "dereg_reason": ("avregistreringsorsak",),
    "proceedings": ("pagandeavvecklingselleromstruktureringsforfarande",),
    "address": ("postadress", "adress", "postadress_organisation"),
    "description": ("verksamhetsbeskrivning", "verksamhet"),
}

# Organisation forms we allow at all. Sole traders (enskild näringsidkare) are
# identified by personnummer and are deliberately excluded: no private persons.
FORM_CODES: dict[str, str] = {
    "AB": "Aktiebolag",
    "HB": "Handelsbolag",
    "KB": "Kommanditbolag",
    "EK": "Ekonomisk förening",
    "BRF": "Bostadsrättsförening",
    "BF": "Bostadsförening",
    "I": "Ideell förening",
    "EF": "Enskild näringsidkare",
    "E": "Enskild näringsidkare",
}
_FORM_BY_NAME = {v.lower(): k for k, v in FORM_CODES.items() if k not in ("E",)}
EXCLUDED_FORMS = {"EF"}

_POSTCODE_RE = re.compile(r"^\s*(\d{3})\s?(\d{2})\s*$")
_POSTCODE_INLINE_RE = re.compile(r"\b(\d{3})\s?(\d{2})\b\s*(.*)$")
_DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


@dataclass
class Company:
    orgnr: str
    name: str
    form: str  # normalised code, e.g. "AB"
    reg_date: date | None
    street: str
    postcode: str  # "41101" (digits only) or ""
    city: str
    description: str
    care_of: str = ""  # c/o line; often a private person's name -> not exported by default

    @property
    def postcode_display(self) -> str:
        return f"{self.postcode[:3]} {self.postcode[3:]}" if len(self.postcode) == 5 else self.postcode


def _first(value: str, sep: str) -> str:
    return value.split(sep, 1)[0].strip()


def parse_identity(value: str) -> str | None:
    """'5566778899$ORGNR' -> '5566778899'. Returns None for personal identity numbers."""
    first = _first(_first(value, "|"), "$")
    digits = re.sub(r"\D", "", first)
    if len(digits) == 10:
        # Third digit >= 2 is the rule for legal-person org numbers; personnummer
        # (10 digits, YYMMDD) have month 01-12 in positions 3-4 → third digit 0/1.
        if digits[2] in "01":
            return None
        return digits
    if len(digits) == 12 and digits.startswith("16"):
        # Some systems prefix org numbers with century '16'.
        return parse_identity(digits[2:])
    return None  # 12-digit personnummer / samordningsnummer or garbage


def _code(part: str) -> str:
    """'AB-ORGFO' -> 'AB', 'FORETAGSNAMN-ORGNAM' -> 'FORETAGSNAMN', 'AB' -> 'AB'."""
    part = part.strip()
    return part.rsplit("-", 1)[0] if re.fullmatch(r"[A-ZÅÄÖ0-9_]+-[A-Z]+", part) else part


def parse_name(value: str) -> str:
    """Primary company name: the list item typed FORETAGSNAMN, else the first item."""
    items = [i for i in value.split("|") if i.strip()]
    for item in items:
        parts = item.split("$")
        if len(parts) > 1 and _code(parts[1]) == "FORETAGSNAMN":
            return parts[0].strip()
    return _first(items[0], "$") if items else ""


def parse_form(value: str) -> str:
    v = _first(value, "|")
    parts = [p.strip() for p in v.split("$") if p.strip()]
    for p in parts:
        up = _code(p).upper()
        if up in FORM_CODES:
            return "EF" if up == "E" else up
        if p.lower() in _FORM_BY_NAME:
            return _FORM_BY_NAME[p.lower()]
    return parts[0].upper() if parts else ""


def parse_date(value: str) -> date | None:
    m = _DATE_RE.search(value or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _city(c: str) -> str:
    return c.title() if c.isupper() else c


def parse_address_full(value: str) -> tuple[str, str, str, str]:
    """Return (street, care_of, postcode, city). Real layout: street$c/o$CITY$POSTNR$COUNTRY."""
    parts = [p.strip() for p in _first(value, "|").split("$")]
    if len(parts) >= 4 and _POSTCODE_RE.match(parts[3]):
        m = _POSTCODE_RE.match(parts[3])
        return parts[0], parts[1], m.group(1) + m.group(2), _city(parts[2])
    street, postcode, city = parse_address(value)
    return street, "", postcode, city


def parse_address(value: str) -> tuple[str, str, str]:
    """Fallback parser for unknown layouts: locate the postcode segment."""
    v = _first(value, "|")
    parts = [p.strip() for p in v.split("$")]
    for i, p in enumerate(parts):
        m = _POSTCODE_RE.match(p)
        if m:
            postcode = m.group(1) + m.group(2)
            city = next((q for q in parts[i + 1:] if q and not q.isdigit()), "")
            street = ", ".join(q for q in parts[:i] if q)
            return street, postcode, _city(city)
    # Fallback: "Storgatan 1, 411 01 Göteborg" style single string
    joined = " ".join(p for p in parts if p)
    m = _POSTCODE_INLINE_RE.search(joined)
    if m:
        street = joined[: m.start()].strip(" ,")
        city = m.group(3).strip()
        return street, m.group(1) + m.group(2), city.title() if city.isupper() else city
    return joined, "", ""


def _open_text(path: Path) -> io.TextIOBase:
    """Stream the file (zip or txt) as UTF-8 text. Never loads the ~1 GB file into memory."""
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))] or zf.namelist()
        fb = zf.open(names[0])
    else:
        fb = open(path, "rb")
    return io.TextIOWrapper(fb, encoding="utf-8-sig", errors="replace", newline="")


def _reader(f: io.TextIOBase):
    return csv.reader(f, delimiter=";", quotechar='"', escapechar="\\", doublequote=True)


def _resolve_columns(header: list[str]) -> dict[str, int]:
    norm = [h.strip().strip('"').lower().replace(" ", "_") for h in header]
    cols: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in norm:
                cols[key] = norm.index(a)
                break
    missing = {"identity", "name"} - cols.keys()
    if missing:
        raise ValueError(f"bulk file header lacks required columns {missing}; header={header!r}")
    return cols


def read_header(path: Path) -> list[str]:
    with _open_text(path) as f:
        return next(_reader(f))


def iter_companies(path: Path, stats: dict | None = None) -> Iterator[Company]:
    """Yield active legal-person companies from a bulk file (zip or txt)."""
    stats = stats if stats is not None else {}
    for k in ("rows", "yielded", "skipped_person", "skipped_deregistered", "skipped_proceedings",
              "skipped_form", "bad_rows"):
        stats.setdefault(k, 0)
    f = _open_text(path)
    reader = _reader(f)
    header = next(reader)
    cols = _resolve_columns(header)

    def get(row: list[str], key: str) -> str:
        i = cols.get(key)
        return row[i] if i is not None and i < len(row) else ""

    for row in reader:
        stats["rows"] += 1
        if not row or len(row) != len(header):
            stats["bad_rows"] += 1
            continue
        orgnr = parse_identity(get(row, "identity"))
        if orgnr is None:
            stats["skipped_person"] += 1
            continue
        if get(row, "dereg_date").strip() or get(row, "dereg_reason").strip():
            stats["skipped_deregistered"] += 1
            continue
        if get(row, "proceedings").strip():  # ongoing liquidation / bankruptcy / reconstruction
            stats["skipped_proceedings"] += 1
            continue
        form = parse_form(get(row, "form"))
        if form in EXCLUDED_FORMS:
            stats["skipped_form"] += 1
            continue
        street, care_of, postcode, city = parse_address_full(get(row, "address"))
        stats["yielded"] += 1
        yield Company(
            orgnr=orgnr,
            name=parse_name(get(row, "name")),
            form=form,
            reg_date=parse_date(get(row, "reg_date")) or _date_from_name_field(get(row, "name")),
            street=street,
            postcode=postcode,
            city=city,
            description=" ".join(get(row, "description").replace("$", " ").replace("|", " ").split()),
            care_of=care_of,
        )


def _date_from_name_field(value: str) -> date | None:
    # Bolagsverket describes organisationsnamn as name$nametype$registration date$...
    parts = _first(value, "|").split("$")
    for p in parts[1:]:
        d = parse_date(p)
        if d:
            return d
    return None
