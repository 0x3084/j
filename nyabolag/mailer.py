"""SMTP mailer. Without SMTP_HOST, mails are written to data/outbox/*.eml (preview, nothing is sent).

In TEST MODE (NYABOLAG_TEST_MODE=1) the subject is prefixed "[TEST]" and only addresses listed in
TEST_RECIPIENTS may receive mail; any other recipient raises MailRefused, before anything is written
or sent, so a test run can never reach a real customer.
"""
from __future__ import annotations

import re
import smtplib
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
    if not cfg.smtp_host:
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
