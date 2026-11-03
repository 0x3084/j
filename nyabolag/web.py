"""Flask app: landing + signup, Stripe webhook, magic-link login, customer dashboard, health check."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import billing
from .config import Config
from .db import connect, get_filters, tx
from .delivery import normalise_filters, preview, verified_cutoff
from .mailer import send_mail

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOGIN_MAX_AGE = 60 * 60  # magic links valid for 1 hour


def create_app(cfg: Config | None = None) -> Flask:
    cfg = cfg or Config()
    if cfg.base_url.startswith("https://") and (cfg.secret_key.startswith("dev-") or len(cfg.secret_key) < 32):
        raise RuntimeError("SECRET_KEY must be a random value of at least 32 characters in production")
    cfg.ensure_dirs()
    app = Flask(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=cfg.base_url.startswith("https://"))
    signer = URLSafeTimedSerializer(cfg.secret_key, salt="login")

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect(cfg.db_path)
        return g.db

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
                                "form-action 'self' https://checkout.stripe.com https://billing.stripe.com")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")  # magic-link tokens live in URLs
        if request.path.startswith(("/dashboard", "/download", "/auth")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.teardown_appcontext
    def _close(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def current_customer() -> sqlite3.Row | None:
        cid = session.get("customer_id")
        if not cid:
            return None
        return db().execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()

    def send_login_link(email: str) -> None:
        token = signer.dumps(email)
        link = f"{cfg.base_url}/auth/{token}"
        send_mail(cfg, email, "Din inloggningslänk",
                  f"Klicka för att logga in (giltig i 1 timme):\n{link}\n\nHar du inte bett om detta kan du ignorera mejlet.")

    # ---------- public ----------
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/checkout")
    def checkout():
        email = request.form.get("email", "").strip().lower()
        company = request.form.get("company_name", "").strip()
        if not EMAIL_RE.match(email):
            return render_template("index.html", error="Ange en giltig e-postadress."), 400
        filters = normalise_filters({
            "postcode_prefixes": request.form.get("postcode_prefixes", ""),
            "cities": request.form.get("cities", ""),
        })
        if not (filters["postcode_prefixes"] or filters["cities"]):
            return render_template("index.html", error="Ange minst ett postnummerprefix eller en ort."), 400
        return redirect(billing.create_checkout(cfg, email, company, filters), code=303)

    @app.get("/tack")
    def thanks():
        return render_template("message.html", title="Tack!",
                               message="Betalningen är klar. Du får ett mejl med inloggningslänk inom några minuter. "
                                       "Första listan kommer på måndag.")

    @app.post("/stripe/webhook")
    def stripe_webhook():
        payload = request.get_data()
        try:
            event = billing.verify_event(cfg, payload, request.headers.get("Stripe-Signature", ""))
        except Exception:
            abort(400)
        result = billing.handle_event(db(), event)
        if result.startswith("activated "):
            send_login_link(result.removeprefix("activated "))
            result = "activated"  # don't echo personal data in responses/logs
        return jsonify(ok=True, result=result)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            if db().execute("SELECT 1 FROM customers WHERE email = ?", (email,)).fetchone():
                send_login_link(email)
            # Same answer either way: don't reveal who is a customer.
            return render_template("message.html", title="Kolla din inkorg",
                                   message="Om adressen finns hos oss har vi skickat en inloggningslänk.")
        return render_template("login.html")

    @app.get("/auth/<token>")
    def auth(token: str):
        try:
            email = signer.loads(token, max_age=LOGIN_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return render_template("message.html", title="Länken fungerar inte",
                                   message="Länken är ogiltig eller har gått ut. Begär en ny."), 400
        row = db().execute("SELECT id FROM customers WHERE email = ?", (email,)).fetchone()
        if not row:
            abort(404)
        session.clear()
        session["customer_id"] = row["id"]
        return redirect(url_for("dashboard"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    # ---------- customer ----------
    @app.get("/dashboard")
    def dashboard():
        cust = current_customer()
        if not cust:
            return redirect(url_for("login"))
        filters = get_filters(cust)
        deliveries = db().execute(
            "SELECT * FROM deliveries WHERE customer_id = ? ORDER BY id DESC LIMIT 52", (cust["id"],)).fetchall()
        sample = preview(db(), filters, 4, verified_cutoff(cfg))
        return render_template("dashboard.html", c=cust, f=filters, deliveries=deliveries,
                               preview_count=len(sample), preview_rows=sample[:10], saved=request.args.get("saved"))

    @app.post("/dashboard/filters")
    def update_filters():
        cust = current_customer()
        if not cust:
            abort(401)
        filters = normalise_filters({k: request.form.get(k, "") for k in
                                     ("postcode_prefixes", "cities", "keywords")} |
                                    {"forms": request.form.getlist("forms")})
        with tx(db()):
            db().execute("UPDATE customers SET filters = ? WHERE id = ?", (json.dumps(filters), cust["id"]))
        return redirect(url_for("dashboard", saved=1))

    @app.get("/download/<int:delivery_id>")
    def download(delivery_id: int):
        cust = current_customer()
        if not cust:
            abort(401)
        d = db().execute("SELECT * FROM deliveries WHERE id = ? AND customer_id = ?",
                         (delivery_id, cust["id"])).fetchone()
        if not d or not Path(d["csv_path"]).exists():
            abort(404)
        return send_file(Path(d["csv_path"]).resolve(), mimetype="text/csv", as_attachment=True,
                         download_name=f"nya-bolag-{d['sent_at'][:10]}.csv")

    @app.post("/billing")
    def billing_portal():
        cust = current_customer()
        if not cust or not cust["stripe_customer_id"]:
            abort(401)
        return redirect(billing.portal_url(cfg, cust["stripe_customer_id"]), code=303)

    # ---------- ops ----------
    @app.get("/healthz")
    def healthz():
        row = db().execute("SELECT imported_at FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return jsonify(ok=False, reason="no snapshot imported yet"), 503
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["imported_at"])
        ok = age.days <= cfg.stale_after_days
        return jsonify(ok=ok, last_import=row["imported_at"], age_days=age.days), (200 if ok else 503)

    return app
