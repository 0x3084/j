"""Minimal SMTP mailer. Without SMTP_HOST, mails are written to data/outbox/ (dev/test)."""
from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from datetime import datetime

from .config import Config


def send_mail(cfg: Config, to: str, subject: str, body: str,
              attachment: tuple[str, bytes, str] | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        name, data, mime = attachment
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

    if not cfg.smtp_host:
        cfg.ensure_dirs()
        safe = re.sub(r"[^A-Za-z0-9@._-]", "_", to)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        (cfg.outbox_dir / f"{stamp}-{safe}.eml").write_bytes(bytes(msg))
        return
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
        s.starttls()
        if cfg.smtp_user:
            s.login(cfg.smtp_user, cfg.smtp_password)
        s.send_message(msg)
