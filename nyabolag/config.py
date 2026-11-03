"""All configuration comes from environment variables (see deploy/.env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(_env("NYABOLAG_DATA_DIR", "./data")))
    base_url: str = field(default_factory=lambda: _env("BASE_URL", "http://localhost:5000").rstrip("/"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-insecure-change-me"))
    bulkfile_url: str = field(default_factory=lambda: _env("BULKFILE_URL", ""))
    stripe_secret_key: str = field(default_factory=lambda: _env("STRIPE_SECRET_KEY", ""))
    stripe_webhook_secret: str = field(default_factory=lambda: _env("STRIPE_WEBHOOK_SECRET", ""))
    stripe_price_id: str = field(default_factory=lambda: _env("STRIPE_PRICE_ID", ""))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD", ""))
    # "smtp" (needs SMTP_HOST), "resend-api" (HTTPS, Resend), or "outbox" (preview files only).
    # Default: smtp if SMTP_HOST is set, else outbox. The Resend key is read from RESEND_API_KEY,
    # falling back to SMTP_PASSWORD (Resend uses the same key for both).
    mail_transport: str = field(default_factory=lambda: _env(
        "MAIL_TRANSPORT", "smtp" if _env("SMTP_HOST") else "outbox"))
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY") or _env("SMTP_PASSWORD"))
    resend_api_url: str = field(default_factory=lambda: _env("RESEND_API_URL", "https://api.resend.com/emails"))
    mail_from: str = field(default_factory=lambda: _env("MAIL_FROM", "nyabolag <noreply@localhost>"))
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", ""))
    # Commercial / mail settings
    brand: str = field(default_factory=lambda: _env("BRAND", "Veckans Nya Bolag"))
    price_sek_month: int = field(default_factory=lambda: int(_env("PRICE_SEK_MONTH", "249")))
    vat_text: str = field(default_factory=lambda: _env("VAT_TEXT", "[moms-text: momsbefriad / exkl. moms]"))
    reply_to: str = field(default_factory=lambda: _env("REPLY_TO", ""))
    # TEST MODE: subjects get a [TEST] prefix, every e-mail carries a test banner, and mail can
    # only go to addresses in TEST_RECIPIENTS (comma-separated). Everything else is refused.
    test_mode: bool = field(default_factory=lambda: _env("NYABOLAG_TEST_MODE", "0") in ("1", "true", "yes"))
    test_recipients: tuple = field(default_factory=lambda: tuple(
        a.strip().lower() for a in _env("TEST_RECIPIENTS", "").split(",") if a.strip()))
    healthcheck_url: str = field(default_factory=lambda: _env("HEALTHCHECK_URL", ""))
    # A company counts as newly registered only if its registration date (when present)
    # is at most this many days before the snapshot date.
    new_max_age_days: int = field(default_factory=lambda: int(_env("NEW_MAX_AGE_DAYS", "60")))
    # Customer deliveries only contain companies whose reklamspärr status was verified via the
    # official API within this many days. Missing or older statuses count as unverified.
    reklamsparr_max_age_days: int = field(default_factory=lambda: int(_env("REKLAMSPARR_MAX_AGE_DAYS", "30")))
    # Bolagsverket "API för värdefulla datamängder" (free; credentials via Kundanmälan form)
    hvd_client_id: str = field(default_factory=lambda: _env("HVD_CLIENT_ID", ""))
    hvd_client_secret: str = field(default_factory=lambda: _env("HVD_CLIENT_SECRET", ""))
    hvd_token_url: str = field(default_factory=lambda: _env(
        "HVD_TOKEN_URL", "https://portal.api.bolagsverket.se/oauth2/token"))
    hvd_api_base: str = field(default_factory=lambda: _env(
        "HVD_API_BASE", "https://gw.api.bolagsverket.se/vardefulla-datamangder/v1"))
    hvd_scope: str = field(default_factory=lambda: _env("HVD_SCOPE", "vardefulla-datamangder:read"))
    stale_after_days: int = field(default_factory=lambda: int(_env("STALE_AFTER_DAYS", "9")))

    @property
    def dashboard_enabled(self) -> bool:
        """The web dashboard only exists once deployed on https; until then e-mails say 'reply to change'."""
        return self.base_url.startswith("https://")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nyabolag.sqlite3"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def deliveries_dir(self) -> Path:
        return self.data_dir / "deliveries"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.deliveries_dir, self.outbox_dir):
            d.mkdir(parents=True, exist_ok=True)
