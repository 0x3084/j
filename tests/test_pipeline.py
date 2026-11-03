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

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 2)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("NYABOLAG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    c = Config()
    c.ensure_dirs()
    return c


@pytest.fixture
def conn(cfg):
    return connect(cfg.db_path)


# ---------- parsing ----------
def test_parse_identity_excludes_persons():
    assert bulkfile.parse_identity("5560000001$ORGNR") == "5560000001"
    assert bulkfile.parse_identity("198501011234$PERSONNUMMER") is None
    assert bulkfile.parse_identity("8501011234") is None  # 10-digit personnummer
    assert bulkfile.parse_identity("165560000001") == "5560000001"


def test_parse_address_variants():
    assert bulkfile.parse_address("c/o Andersson$Fjällgatan 3$41463$GÖTEBORG$SE") == (
        "c/o Andersson, Fjällgatan 3", "41463", "Göteborg")
    assert bulkfile.parse_address("Storgatan 1, 411 01 Göteborg") == ("Storgatan 1", "41101", "Göteborg")
    assert bulkfile.parse_address("") == ("", "", "")


def test_iter_companies_filters_rows():
    stats = {}
    rows = list(bulkfile.iter_companies(FIX / "bulk_week2.zip", stats))
    orgnrs = {c.orgnr for c in rows}
    assert "5590000002" not in orgnrs  # deregistered
    assert stats["skipped_person"] == 2  # both sole traders
    assert stats["skipped_deregistered"] == 1
    nya = next(c for c in rows if c.orgnr == "5595000003")
    assert nya.name == "Nya Redovisning Väst AB" and nya.form == "AB"
    assert nya.reg_date == date(2026, 10, 28) and nya.city == "Göteborg"


def test_missing_required_column(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text('"foo";"bar"\n"1";"2"\n')
    with pytest.raises(ValueError):
        list(bulkfile.iter_companies(p))


# ---------- diff ----------
def test_baseline_then_new(conn, cfg):
    r1 = ingest(conn, FIX / "bulk_week1.txt", cfg, today=TODAY)
    assert r1["baseline"] and r1["new"] == 0
    r2 = ingest(conn, FIX / "bulk_week2.zip", cfg, today=TODAY)
    # 4 genuinely new; the old company that "reappeared" (reg 2001) is not new
    assert r2["new"] == 4
    assert ingest(conn, FIX / "bulk_week2.zip", cfg, today=TODAY)["skipped"]
    old = conn.execute("SELECT is_new FROM companies WHERE orgnr='5560000077'").fetchone()
    assert old["is_new"] == 0


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
                    "street": "x", "postcode": "41463", "city": "Göteborg", "description": ""}])
    assert data.startswith("﻿".encode())
    text = data.decode("utf-8-sig")
    assert "559500-0003" in text and '"A;B"' in text and "414 63" in text


# ---------- delivery ----------
def _add_customer(conn, email, status="active", **filters):
    conn.execute("INSERT INTO customers (email, status, filters, created_at) VALUES (?,?,?, 'now')",
                 (email, status, json.dumps(normalise_filters(filters))))
    conn.commit()


def test_delivery_idempotent_and_filtered(conn, cfg):
    ingest(conn, FIX / "bulk_week1.txt", cfg, today=TODAY)
    ingest(conn, FIX / "bulk_week2.zip", cfg, today=TODAY)
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


def test_webhook_lifecycle_and_dashboard(client, cfg, conn):
    ingest(conn, FIX / "bulk_week1.txt", cfg, today=TODAY)
    ingest(conn, FIX / "bulk_week2.zip", cfg, today=TODAY)

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


def test_healthz(client, cfg, conn):
    assert client.get("/healthz").status_code == 503
    ingest(conn, FIX / "bulk_week1.txt", cfg, today=TODAY)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["ok"]
