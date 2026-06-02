"""Refresh one wallet end-to-end: ingest + features + bot score.

Usage:
    .venv/bin/python -m scripts.refresh 0xabc...
    .venv/bin/python -m scripts.refresh 0xabc... 0xdef... --max-activity 500
"""

from __future__ import annotations

import argparse

from polyfinder import bot_score, features
from polyfinder.db import init_db
from polyfinder.ingest.all import ingest_wallet_full


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wallets", nargs="+")
    ap.add_argument("--max-activity", type=int, default=None)
    ap.add_argument("--skip-markets", action="store_true", help="Don't refresh market metadata")
    args = ap.parse_args()

    init_db()
    for w in args.wallets:
        print(f"\n--- {w} ---")
        summary = ingest_wallet_full(
            w, refresh_markets=not args.skip_markets, max_activity=args.max_activity
        )
        print("ingest:", summary)
        f = features.recompute(w)
        if f:
            print(f"features: n_trades={f['n_trades']} pnl={f['realized_pnl']:.2f} "
                  f"age={f['account_age_days']:.1f}d wins={f['n_wins']}/{f['n_resolved_bets']}")
            s = bot_score.recompute(w)
            print(f"bot_score: {s}")


if __name__ == "__main__":
    main()
