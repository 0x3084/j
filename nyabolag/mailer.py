"""Mailer with three transports (MAIL_TRANSPORT): "smtp", "resend-api" (HTTPS) or "outbox"
(preview: data/outbox/*.eml, nothing is sent). Secrets are never printed or logged.

In TEST MODE (NYABOLAG_TEST_MODE=1) the subject is prefixed "[TEST]" and only addresses listed in
TEST_RECIPIENTS may receive mail; any other recipient raises MailRefused, before anything is written
or sent, so a test run can never reach a real customer.
"""
from __future__ import annotations

import base64
import json
import re
import smtplib
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .config import Config


class MailRefused(RuntimeError):
    pass


def build_message(cfg: Config, to: str, subject: str, text: str, html: str | None = None,
                  attachments: list[tuple[str, bytes, str]] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = to
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg["Subject"] = ("[TEST] " if cfg.test_mode else "") + subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg.mail_from.rsplit("@", 1)[-1].strip("> ") or "localhost")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


def send_mail(cfg: Config, to: str, subject: str, body: str, html: str | None = None,
              attachment: tuple[str, bytes, str] | None = None,
              attachments: list[tuple[str, bytes, str]] | None = None) -> Path | None:
    """Send (or, without SMTP, write a preview). Returns the preview path when written to the outbox."""
    if cfg.test_mode and to.strip().lower() not in cfg.test_recipients:
        raise MailRefused(f"TEST MODE: {to} is not in TEST_RECIPIENTS; nothing sent")
    atts = list(attachments or []) + ([attachment] if attachment else [])
    msg = build_message(cfg, to, subject, body, html, atts)
    if cfg.mail_transport == "resend-api":
        return _send_resend(cfg, msg, to, subject, body, html, atts)
    if cfg.mail_transport != "smtp" or not cfg.smtp_host:
        cfg.ensure_dirs()
        safe = re.sub(r"[^A-Za-z0-9@._-]", "_", to)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        path = cfg.outbox_dir / f"{stamp}-{safe}.eml"
        path.write_bytes(bytes(msg))
        return path
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
        s.starttls()
        if cfg.smtp_user:
            s.login(cfg.smtp_user, cfg.smtp_password)
        s.send_message(msg)
    return None


class MailError(RuntimeError):
    pass


def _send_resend(cfg: Config, msg: EmailMessage, to: str, subject: str, text: str, html: str | None,
                 atts: list[tuple[str, bytes, str]]) -> None:
    """POST https://api.resend.com/emails. Raises MailError with Resend's message (never the key)."""
    if not cfg.resend_api_key:
        raise MailError("RESEND_API_KEY (or SMTP_PASSWORD) is not set")
    payload = {"from": cfg.mail_from, "to": [to], "subject": msg["Subject"], "text": text}
    if html:
        payload["html"] = html
    if cfg.reply_to:
        payload["reply_to"] = cfg.reply_to
    if atts:
        payload["attachments"] = [{"filename": n, "content": base64.b64encode(d).decode()} for n, d, _ in atts]
    req = urllib.request.Request(cfg.resend_api_url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {cfg.resend_api_key}", "Content-Type": "application/json",
        "User-Agent": "nyabolag/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise MailError(f"Resend refused the e-mail: HTTP {e.code} {detail}".strip()) from None
    except urllib.error.URLError as e:
        raise MailError(f"cannot reach Resend: {e.reason}") from None
    print(f"sent via Resend to {to}, id {out.get('id', '?')}")
    return None
