"""Stripe subscription billing. Stripe is the source of truth; we mirror status via webhooks."""
from __future__ import annotations

import json
import sqlite3

import stripe

from .config import Config
from .db import now_iso, tx
from .delivery import normalise_filters

# Stripe subscription status -> our status
STATUS_MAP = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "pending",
    "incomplete_expired": "canceled",
    "canceled": "canceled",
    "paused": "canceled",
}


def _client(cfg: Config) -> None:
    if not cfg.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    stripe.api_key = cfg.stripe_secret_key


def create_checkout(cfg: Config, email: str, company_name: str, filters: dict) -> str:
    """Return the URL of a hosted Stripe Checkout page for the subscription."""
    _client(cfg)
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": cfg.stripe_price_id, "quantity": 1}],
        customer_email=email,
        billing_address_collection="required",
        tax_id_collection={"enabled": True},
        allow_promotion_codes=True,
        metadata={"company_name": company_name[:200], "filters": json.dumps(filters)[:490]},
        success_url=f"{cfg.base_url}/tack",
        cancel_url=f"{cfg.base_url}/",
    )
    return session.url


def portal_url(cfg: Config, stripe_customer_id: str) -> str:
    _client(cfg)
    s = stripe.billing_portal.Session.create(customer=stripe_customer_id, return_url=f"{cfg.base_url}/dashboard")
    return s.url


def handle_event(conn: sqlite3.Connection, event: dict) -> str:
    """Apply one verified Stripe event. Returns a short description. Idempotent by event id."""
    if conn.execute("SELECT 1 FROM stripe_events WHERE id = ?", (event["id"],)).fetchone():
        return "duplicate"
    etype = event["type"]
    obj = event["data"]["object"]
    result = "ignored"
    with tx(conn):
        if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
            email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
            meta = obj.get("metadata") or {}
            try:
                filters = normalise_filters(json.loads(meta.get("filters") or "{}"))
            except (json.JSONDecodeError, AttributeError, TypeError):
                filters = normalise_filters({})
            existing = conn.execute("SELECT id FROM customers WHERE email = ?", (email,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE customers SET stripe_customer_id=?, stripe_subscription_id=?, status='active', "
                    "company_name=COALESCE(NULLIF(?, ''), company_name), filters=? WHERE id=?",
                    (obj.get("customer"), obj.get("subscription"), meta.get("company_name", ""),
                     json.dumps(filters), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO customers (email, company_name, stripe_customer_id, stripe_subscription_id, "
                    "status, filters, created_at) VALUES (?,?,?,?, 'active', ?, ?)",
                    (email, meta.get("company_name", ""), obj.get("customer"), obj.get("subscription"),
                     json.dumps(filters), now_iso()),
                )
            result = f"activated {email}"
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            status = "canceled" if etype.endswith("deleted") else STATUS_MAP.get(obj.get("status"), "pending")
            conn.execute(
                "UPDATE customers SET status=?, stripe_subscription_id=? WHERE stripe_customer_id=?",
                (status, obj.get("id"), obj.get("customer")),
            )
            result = f"status {status}"
        elif etype == "invoice.payment_failed":
            conn.execute("UPDATE customers SET status='past_due' WHERE stripe_customer_id=?", (obj.get("customer"),))
            result = "past_due"
        conn.execute("INSERT INTO stripe_events (id, type, received_at) VALUES (?,?,?)", (event["id"], etype, now_iso()))
    return result


def verify_event(cfg: Config, payload: bytes, sig_header: str) -> dict:
    """Raise if the signature is invalid; return the event as a plain dict."""
    stripe.Webhook.construct_event(payload, sig_header, cfg.stripe_webhook_secret)
    return json.loads(payload)
