"""Parser for Bolagsverket's free weekly bulk file (bolagsverket_bulkfil.zip).

Known facts (Bolagsverket "Nedladdningsbara filer" + third-party notes, 2025-2026):
  * zip containing one .txt file, updated weekly
  * semicolon separated, quoted, with a header row
  * structured values flattened into one field with '$' as structure separator
    and '|' as list separator, e.g. organisationsidentitet = "5566778899$ORGNR"
  * a handful of rows contain badly escaped quotes

The exact column layout has NOT been verified against a real file from this
environment. Columns are therefore located by header name using COLUMN_ALIASES,
and every structured field is parsed defensively. Run `nyabolag inspect <file>`
on a real download and adjust the aliases if needed (validation Phase 0).
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


def parse_name(value: str) -> str:
    return _first(_first(value, "|"), "$")


def parse_form(value: str) -> str:
    v = _first(value, "|")
    parts = [p.strip() for p in v.split("$") if p.strip()]
    for p in parts:
        up = p.upper()
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


def parse_address(value: str) -> tuple[str, str, str]:
    """Return (street, postcode, city) from a '$'-structured address field.

    The segment order is not documented to us, so locate the postcode segment and
    treat the following segment as the city and the earlier non-empty segments as
    the street / c/o lines.
    """
    v = _first(value, "|")
    parts = [p.strip() for p in v.split("$")]
    for i, p in enumerate(parts):
        m = _POSTCODE_RE.match(p)
        if m:
            postcode = m.group(1) + m.group(2)
            city = next((q for q in parts[i + 1:] if q and not q.isdigit()), "")
            street = ", ".join(q for q in parts[:i] if q)
            return street, postcode, city.title() if city.isupper() else city
    # Fallback: "Storgatan 1, 411 01 Göteborg" style single string
    joined = " ".join(p for p in parts if p)
    m = _POSTCODE_INLINE_RE.search(joined)
    if m:
        street = joined[: m.start()].strip(" ,")
        city = m.group(3).strip()
        return street, m.group(1) + m.group(2), city.title() if city.isupper() else city
    return joined, "", ""


def _open_text(path: Path) -> io.TextIOBase:
    raw: bytes
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))] or zf.namelist()
            raw = zf.read(names[0])
    else:
        raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return io.StringIO(raw.decode(enc), newline="")
        except UnicodeDecodeError:
            continue
    raise ValueError("cannot decode bulk file")


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
    f = _open_text(path)
    sample = f.read(4096)
    f.seek(0)
    delim = ";" if sample.count(";") >= sample.count("\t") else "\t"
    return next(csv.reader(f, delimiter=delim))


def iter_companies(path: Path, stats: dict | None = None) -> Iterator[Company]:
    """Yield active legal-person companies from a bulk file (zip or txt)."""
    stats = stats if stats is not None else {}
    for k in ("rows", "yielded", "skipped_person", "skipped_deregistered", "skipped_form", "bad_rows"):
        stats.setdefault(k, 0)
    f = _open_text(path)
    sample = f.read(4096)
    f.seek(0)
    delim = ";" if sample.count(";") >= sample.count("\t") else "\t"
    reader = csv.reader(f, delimiter=delim)
    cols = _resolve_columns(next(reader))

    def get(row: list[str], key: str) -> str:
        i = cols.get(key)
        return row[i] if i is not None and i < len(row) else ""

    for row in reader:
        stats["rows"] += 1
        if not row or len(row) <= cols["identity"]:
            stats["bad_rows"] += 1
            continue
        orgnr = parse_identity(get(row, "identity"))
        if orgnr is None:
            stats["skipped_person"] += 1
            continue
        if get(row, "dereg_date").strip() or get(row, "dereg_reason").strip():
            stats["skipped_deregistered"] += 1
            continue
        form = parse_form(get(row, "form"))
        if form in EXCLUDED_FORMS:
            stats["skipped_form"] += 1
            continue
        street, postcode, city = parse_address(get(row, "address"))
        stats["yielded"] += 1
        yield Company(
            orgnr=orgnr,
            name=parse_name(get(row, "name")),
            form=form,
            reg_date=parse_date(get(row, "reg_date")) or _date_from_name_field(get(row, "name")),
            street=street,
            postcode=postcode,
            city=city,
            description=get(row, "description").replace("$", " ").replace("|", " ").strip(),
        )


def _date_from_name_field(value: str) -> date | None:
    # Bolagsverket describes organisationsnamn as name$nametype$registration date$...
    parts = _first(value, "|").split("$")
    for p in parts[1:]:
        d = parse_date(p)
        if d:
            return d
    return None
