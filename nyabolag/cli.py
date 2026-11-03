"""Command line: `python -m nyabolag.cli <command>`."""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
import traceback
import urllib.request
from datetime import date
from itertools import islice
from pathlib import Path

from .bulkfile import iter_companies, read_header
from .config import Config
from .db import connect, now_iso, tx
from .delivery import deliver_all, export, normalise_filters, verified_cutoff
from .ingest import fetch, ingest
from .mailer import send_mail
from .reklamsparr import candidates, import_file, verify

MAX_VERIFY_FAILURE_RATE = 0.05  # above this, no deliveries are sent that week


class _JobLock:
    """Prevents two weekly runs (e.g. timer + manual) from overlapping."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another nyabolag job is running")
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _ping(url: str) -> None:
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as exc:  # monitoring must never break the job
        print(f"healthcheck ping failed: {exc}", file=sys.stderr)


def cmd_inspect(args, cfg):
    path = Path(args.file)
    print("header:", read_header(path))
    stats: dict = {}
    for c in islice(iter_companies(path, stats), args.n):
        print(c)
    print("stats (first rows only):", stats)


def cmd_fetch(args, cfg):
    print(fetch(cfg))


def cmd_ingest(args, cfg):
    conn = connect(cfg.db_path)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    print(json.dumps(ingest(conn, Path(args.file), cfg, today=as_of), default=str, indent=2))


def cmd_import_reklamsparr(args, cfg):
    conn = connect(cfg.db_path)
    print(json.dumps(import_file(conn, Path(args.file))))


def cmd_stats(args, cfg):
    conn = connect(cfg.db_path)
    for s in conn.execute("SELECT * FROM snapshots ORDER BY id").fetchall():
        print(dict(s))
    print("\nnew companies in latest snapshot by 3-digit postcode (top 25):")
    rows = conn.execute(
        "SELECT substr(postcode,1,3) p, COUNT(*) n FROM companies WHERE is_new=1 AND is_shelf=0 AND "
        "first_snapshot_id=(SELECT MAX(id) FROM snapshots) GROUP BY p ORDER BY n DESC LIMIT 25").fetchall()
    for r in rows:
        print(f"  {r['p'] or '???'}: {r['n']}")


def cmd_export(args, cfg):
    conn = connect(cfg.db_path)
    filters = {"postcode_prefixes": args.postcodes, "cities": args.cities, "forms": args.forms,
               "keywords": args.keywords}
    verified = None if args.include_unverified else verified_cutoff(cfg)
    n = export(conn, filters, args.snapshots, Path(args.out), verified)
    note = " (INTERNAL: includes unverified reklamspärr)" if verified is None else " (reklamspärr verified)"
    print(f"wrote {n} companies to {args.out}{note}")


def cmd_add_customer(args, cfg):
    """Concierge/manual customer, e.g. one who paid via a Stripe Payment Link."""
    conn = connect(cfg.db_path)
    filters = normalise_filters({"postcode_prefixes": args.postcodes, "cities": args.cities,
                                 "forms": args.forms, "keywords": args.keywords, "label": args.label})
    with tx(conn):
        conn.execute(
            "INSERT INTO customers (email, company_name, status, filters, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET filters=excluded.filters, status=excluded.status",
            (args.email.lower(), args.company or "", args.status, json.dumps(filters), now_iso()),
        )
    print("ok")


def _area_filters(args) -> list[dict]:
    if not (args.postcodes or args.cities):
        return []
    return [normalise_filters({"postcode_prefixes": args.postcodes, "cities": args.cities, "forms": args.forms})]


def cmd_verify_reklamsparr(args, cfg):
    """Verify reklamspärr in Bolagsverket's HVD API for companies that customers would receive."""
    conn = connect(cfg.db_path)
    todo = candidates(conn, cfg, _area_filters(args), args.snapshots)[: args.limit]
    minutes = len(todo) * 1.1 / 60
    print(f"{len(todo)} companies need a check (about {minutes:.1f} min at the API rate limit)")
    if args.dry_run or not todo:
        return
    with _JobLock(cfg.data_dir / "job.lock"):
        print(json.dumps(verify(conn, cfg, todo)))


def cmd_purge(args, cfg):
    """Data retention: delete delivered CSVs and API evidence older than --days, keep 2 newest bulk files."""
    cutoff = time.time() - args.days * 86400
    removed = 0
    for d in (cfg.deliveries_dir, cfg.raw_dir / "api"):
        if d.exists():
            for f in d.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
    bulk = sorted(cfg.raw_dir.glob("bulkfil-*.zip"), key=lambda f: f.stat().st_mtime)
    for f in bulk[:-2]:
        f.unlink()
        removed += 1
    print(f"removed {removed} files")


def cmd_welcome(args, cfg):
    """Send (or preview, without SMTP) the welcome e-mail to an existing customer."""
    from .db import get_filters
    from .emails import welcome_email
    conn = connect(cfg.db_path)
    cust = conn.execute("SELECT * FROM customers WHERE email = ?", (args.email.lower(),)).fetchone()
    if not cust:
        raise SystemExit(f"no customer {args.email}")
    subject, text, html = welcome_email(cfg, cust, get_filters(cust))
    path = send_mail(cfg, cust["email"], subject, text, html=html)
    print(f"welcome e-mail {'written to ' + str(path) if path else 'sent'}")


def cmd_deliver(args, cfg):
    conn = connect(cfg.db_path)
    print(json.dumps(deliver_all(conn, cfg), indent=2))


def cmd_run_weekly(args, cfg):
    """fetch → ingest → verify reklamspärr → deliver, with monitoring. For a systemd timer / cron."""
    lock = _JobLock(cfg.data_dir / "job.lock")
    lock.__enter__()
    conn = connect(cfg.db_path)
    with tx(conn):
        run_id = conn.execute("INSERT INTO job_runs (started_at) VALUES (?)", (now_iso(),)).lastrowid
    try:
        path = Path(args.file) if args.file else fetch(cfg)
        result = ingest(conn, path, cfg)
        if not result["skipped"] and result.get("yielded", 1) == 0:
            raise RuntimeError("bulk file parsed to zero companies – format change?")
        if not result["skipped"] and result.get("bad_rows", 0) > 0.01 * max(result.get("rows", 1), 1):
            raise RuntimeError(f"{result['bad_rows']} of {result['rows']} rows malformed – format change? "
                               "No deliveries sent.")
        todo = candidates(conn, cfg)
        checked = verify(conn, cfg, todo) if todo else {"candidates": 0, "failed": 0}
        if todo and checked["failed"] / len(todo) > MAX_VERIFY_FAILURE_RATE:
            raise RuntimeError(f"reklamspärr verification failed for {checked['failed']}/{len(todo)} "
                               "companies; no deliveries sent. Fix and re-run.")
        sent = deliver_all(conn, cfg)
        msg = json.dumps({"ingest": result, "reklamsparr": checked, "deliveries": sent}, default=str)
        with tx(conn):
            conn.execute("UPDATE job_runs SET finished_at=?, ok=1, message=? WHERE id=?", (now_iso(), msg, run_id))
        print(msg)
        _ping(cfg.healthcheck_url)
    except Exception:
        err = traceback.format_exc()
        with tx(conn):
            conn.execute("UPDATE job_runs SET finished_at=?, ok=0, message=? WHERE id=?", (now_iso(), err, run_id))
        print(err, file=sys.stderr)
        _ping(cfg.healthcheck_url.rstrip("/") + "/fail" if cfg.healthcheck_url else "")
        if cfg.admin_email:
            send_mail(cfg, cfg.admin_email, "nyabolag: veckokörningen misslyckades", err)
        sys.exit(1)
    finally:
        lock.__exit__()


def cmd_serve(args, cfg):
    from .web import create_app
    create_app(cfg).run(host="127.0.0.1", port=args.port, debug=args.debug)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nyabolag")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="show header and first parsed rows of a bulk file")
    s.add_argument("file"); s.add_argument("-n", type=int, default=5); s.set_defaults(fn=cmd_inspect)
    sub.add_parser("fetch", help="download bulk file").set_defaults(fn=cmd_fetch)
    s = sub.add_parser("ingest", help="import a bulk file snapshot"); s.add_argument("file")
    s.add_argument("--as-of", help="file date YYYY-MM-DD (default: today)"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("import-reklamsparr", help="import saved VDM/SCB API responses with reklamspärr")
    s.add_argument("file"); s.set_defaults(fn=cmd_import_reklamsparr)
    sub.add_parser("stats", help="snapshot and volume statistics").set_defaults(fn=cmd_stats)

    def filter_args(sp):
        sp.add_argument("--postcodes", default=""); sp.add_argument("--cities", default="")
        sp.add_argument("--forms", default="AB"); sp.add_argument("--keywords", default="")

    s = sub.add_parser("export", help="manual CSV export (concierge validation)")
    filter_args(s); s.add_argument("--snapshots", type=int, default=1); s.add_argument("--out", default="export.csv")
    s.add_argument("--include-unverified", action="store_true", help="internal use only, never for customers")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("add-customer", help="add/update a manually billed customer")
    s.add_argument("email"); s.add_argument("--company"); s.add_argument("--label", help='area name in e-mails, e.g. "Norrköping och Linköping"')
    s.add_argument("--status", default="active",
                                                                         choices=["active", "canceled", "past_due"])
    filter_args(s); s.set_defaults(fn=cmd_add_customer)
    s = sub.add_parser("verify-reklamsparr", help="check reklamspärr in Bolagsverket's HVD API")
    filter_args(s); s.add_argument("--snapshots", type=int, default=1)
    s.add_argument("--limit", type=int, default=1000); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_verify_reklamsparr)
    s = sub.add_parser("purge", help="data retention clean-up"); s.add_argument("--days", type=int, default=365)
    s.set_defaults(fn=cmd_purge)
    s = sub.add_parser("welcome", help="send/preview the welcome e-mail"); s.add_argument("email")
    s.set_defaults(fn=cmd_welcome)
    sub.add_parser("deliver", help="send pending deliveries").set_defaults(fn=cmd_deliver)
    s = sub.add_parser("run-weekly", help="fetch+ingest+deliver with monitoring")
    s.add_argument("--file", help="use a local file instead of downloading"); s.set_defaults(fn=cmd_run_weekly)
    s = sub.add_parser("serve", help="dev web server"); s.add_argument("--port", type=int, default=5000)
    s.add_argument("--debug", action="store_true"); s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    cfg = Config()
    cfg.ensure_dirs()
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
