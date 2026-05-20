"""Ingest a market's full trade history into the DB.

After running this you can:
  - Get unique participants:  SELECT DISTINCT wallet FROM activities WHERE condition_id=?
  - Run discover.by_market.by_condition_id(...) — which already calls this internally.

Usage:
  .venv/bin/python -m scripts.ingest_market --slug "will-bitcoin-hit-150k-by-june-30-2026"
  .venv/bin/python -m scripts.ingest_market --condition 0x...
"""

from __future__ import annotations

import argparse

from polyfinder.db import init_db
from polyfinder.ingest import activity, markets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--condition")
    ap.add_argument("--max-records", type=int, default=None)
    args = ap.parse_args()

    init_db()
    cid = args.condition
    if args.slug:
        cid = markets.fetch_and_store_market_by_slug(args.slug)
        print("resolved slug ->", cid)
    if not cid:
        raise SystemExit("Pass --slug or --condition")
    markets.fetch_and_store_market_by_condition(cid)
    n = activity.ingest_market_trades(cid, max_records=args.max_records)
    print(f"ingested {n} trade rows for {cid}")


if __name__ == "__main__":
    main()
