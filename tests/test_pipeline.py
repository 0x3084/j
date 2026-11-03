import hashlib
import hmac
import json
import time
from datetime import date
from email import message_from_bytes, policy
from pathlib import Path

import pytest

from nyabolag import bulkfile
from nyabolag.config import Config
from nyabolag.db import connect
from nyabolag.delivery import deliver_all, matches, normalise_filters, to_csv
from nyabolag.ingest import ingest

TODAY = date(2026, 10, 26)  # file date of the real snapshot the format was verified against

# Synthetic rows in the VERIFIED real format of bolagsverket_bulkfil (2026-10-26):
# 11 quoted ';' columns, '$' structure, '|' lists, type-suffixed codes.
HEADER = ["organisationsidentitet", "namnskyddslopnummer", "registreringsland", "organisationsnamn",
          "organisationsform", "avregistreringsdatum", "avregistreringsorsak",
          "pagandeAvvecklingsEllerOmstruktureringsforfarande", "registreringsdatum",
          "verksamhetsbeskrivning", "postadress"]


def row(orgnr, name, form, reg, desc, addr, dereg="", reason="", proc="", idtype="ORGNR-IDORG"):
    return [f"{orgnr}${idtype}", "", "SE-LAND", f"{name}$FORETAGSNAMN-ORGNAM${reg}", f"{form}-ORGFO",
            dereg, reason, proc, reg, desc, addr]


OLD = [
    row("5560000001", "Gamla Bygg AB", "AB", "1999-03-01", "Byggverksamhet", "Storgatan 1$$GÖTEBORG$41101$SE-LAND"),
    row("5590000002", "Avregistrerat AB", "AB", "2010-01-01", "", "Box 1$$STOCKHOLM$11122$SE-LAND",
        dereg="2020-01-01", reason="LIKV-AVORG"),
    row("198501011234", "Kalle Konsult", "EF", "2020-01-01", "Konsult", "Hemvägen 2$$GÖTEBORG$41260$SE-LAND",
        idtype="PERSONNUMMER-IDORG"),
]
NEW = [
    row("5596000003", "Nya Redovisning Väst AB", "AB", "2026-10-20", "Redovisning\noch bokföring",
        "Fjällgatan 3$c/o Andersson$GÖTEBORG$41463$SE-LAND"),
    row("5596000004", "Mölndal Snickeri AB", "AB", "2026-10-21", "Snickeri, bygg och renovering",
        "Kvarngatan 9$$MÖLNDAL$43130$SE-LAND"),
    row("5596000005", "Stockholm Tech AB", "AB", "2026-10-22", "IT-konsult", "Sveavägen 10$$STOCKHOLM$11157$SE-LAND"),
    row("9696000006", "Väst HB", "HB", "2026-10-22", "Handel", "Hamngatan 4$$GÖTEBORG$41106$SE-LAND"),
    row("5596000008", "Konkursat AB", "AB", "2026-10-01", "X", "Gatan 1$$GÖTEBORG$41107$SE-LAND",
        proc="KK-AVOMFO"),
    row("199001011234", "Lisa Frisör", "EF", "2026-10-22", "Frisör", "Hemgatan 1$$GÖTEBORG$41301$SE-LAND",
        idtype="PERSONNUMMER-IDORG"),
] + [row(f"55960001{i:02d}", f"Grundbulten {163100 + i} AB", "AB", "2026-10-15", "Lagerbolag",
         "BOX 427$$VÄXJÖ$35106$SE-LAND") for i in range(4)]
# An old company that only now appears in the file (late/corrected record): must NOT be new.
REAPPEARED = [row("5560000077", "Återuppdykt AB", "AB", "2001-05-05", "Gammalt bolag",
                  "Torget 1$$GÖTEBORG$41102$SE-LAND")]


def write_bulk(path: Path, rows: list[list[str]]) -> Path:
    import csv, io, zipfile
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("bolagsverket_bulkfil.txt", buf.getvalue())
    return path


@pytest.fixture
def week1(tmp_path):
    return write_bulk(tmp_path / "w1.zip", OLD)


@pytest.fixture
def week2(tmp_path):
    return write_bulk(tmp_path / "w2.zip", OLD + NEW + REAPPEARED)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("NYABOLAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("REQUIRE_REKLAMSPARR_CHECK", "0")
    c = Config()
    c.ensure_dirs()
    return c


@pytest.fixture
def conn(cfg):
    return connect(cfg.db_path)


# ---------- parsing (real format) ----------
def test_parse_identity_excludes_persons():
    assert bulkfile.parse_identity("5596028927$ORGNR-IDORG") == "5596028927"
    assert bulkfile.parse_identity("198501011234$PERSONNUMMER-IDORG") is None
    assert bulkfile.parse_identity("8501011234") is None  # 10-digit personnummer
    assert bulkfile.parse_identity("165560000001") == "5560000001"


def test_parse_real_address_and_codes():
    assert bulkfile.parse_address_full("Lagrådsgatan 16b$C/o Abdullah$ESKILSTUNA$63235$SE-LAND") == (
        "Lagrådsgatan 16b", "C/o Abdullah", "63235", "Eskilstuna")
    assert bulkfile.parse_address_full("Storgatan 1, 411 01 Göteborg") == ("Storgatan 1", "", "41101", "Göteborg")
    assert bulkfile.parse_form("HB-ORGFO") == "HB" and bulkfile.parse_form("AB") == "AB"
    assert bulkfile.parse_name("Alt$SARS_FORNAMN-ORGNAM$2020-01-01|Huvud AB$FORETAGSNAMN-ORGNAM$2026-09-21") == "Huvud AB"


def test_iter_companies_filters_rows(week2):
    stats = {}
    rows = list(bulkfile.iter_companies(week2, stats))
    orgnrs = {c.orgnr for c in rows}
    assert "5590000002" not in orgnrs and "5596000008" not in orgnrs
    assert stats["skipped_person"] == 2 and stats["skipped_deregistered"] == 1
    assert stats["skipped_proceedings"] == 1 and stats["bad_rows"] == 0
    nya = next(c for c in rows if c.orgnr == "5596000003")
    assert nya.name == "Nya Redovisning Väst AB" and nya.form == "AB" and nya.care_of == "c/o Andersson"
    assert nya.reg_date == date(2026, 10, 20) and nya.city == "Göteborg" and nya.postcode == "41463"
    assert nya.description == "Redovisning och bokföring"  # embedded line break normalised


def test_missing_required_column(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text('"foo";"bar"\n"1";"2"\n')
    with pytest.raises(ValueError):
        list(bulkfile.iter_companies(p))


# ---------- detection ----------
def test_new_is_decided_by_registration_date(conn, cfg, week1, week2):
    r1 = ingest(conn, week1, cfg, today=TODAY)
    assert r1["first_import"] and r1["new"] == 0  # old companies only
    r2 = ingest(conn, week2, cfg, today=TODAY)
    assert r2["new"] == 8  # 4 real + 4 shelf; the reappeared 2001 company is not new
    assert r2["shelf_flagged"] == 4
    assert ingest(conn, week2, cfg, today=TODAY)["skipped"]
    assert conn.execute("SELECT is_new FROM companies WHERE orgnr='5560000077'").fetchone()[0] == 0


def test_first_import_of_full_history_file_finds_recent_registrations(conn, cfg, week2):
    # The real file holds full history, so a first import must already detect recent ones.
    assert ingest(conn, week2, cfg, today=TODAY)["new"] == 8


def test_reklamsparr_import_and_exclusion(conn, cfg, week2, tmp_path):
    from nyabolag.reklamsparr import import_file
    ingest(conn, week2, cfg, today=TODAY)
    vdm = {"orgnr": "5596000003", "fetched_at": "2026-10-26T20:40:36+00:00", "response": {"organisationer": [
        {"organisationsidentitet": {"identitetsbeteckning": "5596000003"}, "reklamsparr": None}]}}
    scb = {"foretag": [{"peOrgNr": "165596000004", "reklamSparrTyp": 2}]}
    f = tmp_path / "rs.jsonl"
    f.write_text(json.dumps(vdm) + "\n" + json.dumps(scb) + "\n")
    assert import_file(conn, f) == {"checked": 2, "blocked": 1}
    from nyabolag.delivery import new_companies_since
    open_rows = {r["orgnr"] for r in new_companies_since(conn, 0, 1)}
    assert "5596000004" not in open_rows and "5596000003" in open_rows  # opted out -> excluded
    assert not any(r["name"].startswith("Grundbulten") for r in new_companies_since(conn, 0, 1))
    checked_only = {r["orgnr"] for r in new_companies_since(conn, 0, 1, require_reklamsparr_check=True)}
    assert checked_only == {"5596000003"}


# ---------- filters ----------
def test_filters():
    f = normalise_filters({"postcode_prefixes": "414, 431", "cities": "", "forms": ["AB", "EF"]})
    assert f["forms"] == ["AB"] and f["postcode_prefixes"] == ["414", "431"]
    c = {"form": "AB", "postcode": "41463", "city": "Göteborg", "name": "X", "description": "redovisning"}
    assert matches(c, f)
    assert not matches({**c, "postcode": "11157"}, f)
    assert matches({**c, "postcode": "11157", "city": "Göteborg"}, normalise_filters({"cities": "göteborg"}))
    assert not matches(c, normalise_filters({"cities": "göteborg", "keywords": "bygg"}))
    assert not matches({**c, "form": "HB"}, normalise_filters({"cities": "göteborg"}))


def test_csv_is_excel_friendly():
    data = to_csv([{"orgnr": "5595000003", "name": "A;B", "form": "AB", "reg_date": "2026-10-28",
                    "street": "x", "postcode": "41463", "city": "Göteborg", "description": "",
                    "rs_checked_at": None}])
    assert data.startswith("﻿".encode())
    text = data.decode("utf-8-sig")
    assert "559500-0003" in text and '"A;B"' in text and "414 63" in text and "Ej kontrollerad" in text
    assert "c/o" not in text.lower()


# ---------- delivery ----------
def _add_customer(conn, email, status="active", **filters):
    conn.execute("INSERT INTO customers (email, status, filters, created_at) VALUES (?,?,?, 'now')",
                 (email, status, json.dumps(normalise_filters(filters))))
    conn.commit()


def test_delivery_idempotent_and_filtered(conn, cfg, week1, week2):
    ingest(conn, week1, cfg, today=TODAY)
    ingest(conn, week2, cfg, today=TODAY)
    _add_customer(conn, "gbg@example.se", postcode_prefixes="41,43")
    _add_customer(conn, "sthlm@example.se", cities="Stockholm")
    _add_customer(conn, "gone@example.se", status="canceled", cities="Göteborg")
    res = {r["customer_id"]: r["rows"] for r in deliver_all(conn, cfg)}
    assert res == {1: 2, 2: 1}  # AB only by default: Nya Redovisning + Mölndal Snickeri; HB excluded
    assert deliver_all(conn, cfg) == []  # no double-send
    mails = sorted(cfg.outbox_dir.glob("*.eml"))
    assert len(mails) == 2
    msg = message_from_bytes(mails[0].read_bytes(), policy=policy.default)
    assert any(p.get_filename() for p in msg.walk())


# ---------- web + billing ----------
def _signed(payload: bytes, secret: str) -> str:
    t = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


@pytest.fixture
def client(cfg):
    from nyabolag.web import create_app
    app = create_app(cfg)
    app.testing = True
    return app.test_client()


def _event(eid, etype, obj):
    return json.dumps({"id": eid, "object": "event", "type": etype, "data": {"object": obj}}).encode()


def test_webhook_lifecycle_and_dashboard(client, cfg, conn, week1, week2):
    ingest(conn, week1, cfg, today=TODAY)
    ingest(conn, week2, cfg, today=TODAY)

    assert client.post("/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "bad"}).status_code == 400

    obj = {"mode": "subscription", "customer": "cus_1", "subscription": "sub_1",
           "customer_details": {"email": "kund@example.se"},
           "metadata": {"company_name": "Byrån AB", "filters": json.dumps({"postcode_prefixes": ["414"]})}}
    body = _event("evt_1", "checkout.session.completed", obj)
    r = client.post("/stripe/webhook", data=body, headers={"Stripe-Signature": _signed(body, "whsec_test")})
    assert r.status_code == 200 and r.json["result"] == "activated kund@example.se"
    r = client.post("/stripe/webhook", data=body, headers={"Stripe-Signature": _signed(body, "whsec_test")})
    assert r.json["result"] == "duplicate"

    # magic link mail was written to the outbox
    mail = message_from_bytes(sorted(cfg.outbox_dir.glob("*.eml"))[-1].read_bytes(), policy=policy.default)
    link = next(line for line in mail.get_content().splitlines() if "/auth/" in line)
    token = link.rsplit("/auth/", 1)[1].strip()

    assert client.get("/dashboard").status_code == 302
    assert client.get(f"/auth/{token}").status_code == 302
    page = client.get("/dashboard").get_data(as_text=True)
    assert "Byrån AB" in page and "Aktiv" in page and "Nya Redovisning Väst AB" in page

    r = client.post("/dashboard/filters", data={"postcode_prefixes": "431", "forms": ["AB"]})
    assert r.status_code == 302
    assert "Mölndal Snickeri AB" in client.get("/dashboard").get_data(as_text=True)

    deliver_all(conn, cfg)
    d = conn.execute("SELECT id FROM deliveries").fetchone()
    resp = client.get(f"/download/{d['id']}")
    assert resp.status_code == 200 and "Mölndal" in resp.get_data().decode("utf-8-sig")

    body = _event("evt_2", "customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1", "status": "canceled"})
    client.post("/stripe/webhook", data=body, headers={"Stripe-Signature": _signed(body, "whsec_test")})
    assert "Uppsagd" in client.get("/dashboard").get_data(as_text=True)


def test_login_does_not_leak_membership(client):
    r = client.post("/login", data={"email": "nobody@example.se"})
    assert r.status_code == 200 and "Om adressen finns" in r.get_data(as_text=True)


def test_auth_rejects_bad_token(client):
    assert client.get("/auth/garbage").status_code == 400


def test_healthz(client, cfg, conn, week1):
    assert client.get("/healthz").status_code == 503
    ingest(conn, week1, cfg, today=TODAY)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["ok"]
