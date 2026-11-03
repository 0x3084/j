"""Command line: `python -m nyabolag.cli <command>`."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
import urllib.request
from datetime import date
from itertools import islice
from pathlib import Path

from .bulkfile import iter_companies, read_header
from .config import Config
from .db import connect, now_iso, tx
from .delivery import deliver_all, export, normalise_filters
from .ingest import fetch, ingest
from .mailer import send_mail
from .reklamsparr import import_file


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
    n = export(conn, filters, args.snapshots, Path(args.out))
    print(f"wrote {n} companies to {args.out}")


def cmd_add_customer(args, cfg):
    """Concierge/manual customer, e.g. one who paid via a Stripe Payment Link."""
    conn = connect(cfg.db_path)
    filters = normalise_filters({"postcode_prefixes": args.postcodes, "cities": args.cities,
                                 "forms": args.forms, "keywords": args.keywords})
    with tx(conn):
        conn.execute(
            "INSERT INTO customers (email, company_name, status, filters, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET filters=excluded.filters, status=excluded.status",
            (args.email.lower(), args.company or "", args.status, json.dumps(filters), now_iso()),
        )
    print("ok")


def cmd_deliver(args, cfg):
    conn = connect(cfg.db_path)
    print(json.dumps(deliver_all(conn, cfg), indent=2))


def cmd_run_weekly(args, cfg):
    """fetch → ingest → deliver, with monitoring hooks. Intended for a systemd timer / cron."""
    conn = connect(cfg.db_path)
    with tx(conn):
        run_id = conn.execute("INSERT INTO job_runs (started_at) VALUES (?)", (now_iso(),)).lastrowid
    try:
        path = Path(args.file) if args.file else fetch(cfg)
        result = ingest(conn, path, cfg)
        if not result["skipped"] and result.get("yielded", 1) == 0:
            raise RuntimeError("bulk file parsed to zero companies – format change?")
        sent = deliver_all(conn, cfg)
        msg = json.dumps({"ingest": result, "deliveries": sent}, default=str)
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
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("add-customer", help="add/update a manually billed customer")
    s.add_argument("email"); s.add_argument("--company"); s.add_argument("--status", default="active",
                                                                         choices=["active", "canceled", "past_due"])
    filter_args(s); s.set_defaults(fn=cmd_add_customer)
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
