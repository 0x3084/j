"""Paper trading.

  python -m scripts.paper replay --strategy vix_regime_spy --start 2025-11-03 --capital 10000
  python -m scripts.paper live   --strategy <name>     # requires network access to the data feed

Replay mode feeds validated historical bars one at a time through the full live code path
(strategy -> risk manager -> simulated broker -> journal) and is labelled HISTORICAL-REPLAY.
Real-money trading is not implemented.
"""
import argparse
import json
import logging

from qrs.config import PAPER_DIR
from qrs.paper.runner import compare_with_backtest, make_trader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(PAPER_DIR / "alerts.log")])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["replay", "live"])
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--start", default="2025-11-03")
    ap.add_argument("--end", default=None)
    ap.add_argument("--capital", type=float, default=10_000)
    ap.add_argument("--shadow", action="store_true", help="allow a non-approved strategy, labelled SHADOW")
    ap.add_argument("--fresh", action="store_true", help="delete an existing journal for this run first")
    a = ap.parse_args()
    if a.mode == "live":
        raise SystemExit("Live feed mode needs outbound access to the exchange/data API (blocked in this sandbox). "
                         "Use qrs.paper.feeds.BinanceRESTFeed with PaperTrader on a networked host.")
    if a.fresh:
        tag = f"{a.strategy}{'_SHADOW' if a.shadow else ''}"
        (PAPER_DIR / f"{tag}.sqlite").unlink(missing_ok=True)
    pt = make_trader(a.strategy, a.capital, a.start, a.end, shadow=a.shadow)
    pt.run()
    print(json.dumps(compare_with_backtest(pt), indent=1, default=str)[:3000])
