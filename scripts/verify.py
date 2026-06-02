"""End-to-end verification of the polyfinder pipeline.

Runs the steps listed in the plan's Verification section and prints PASS/FAIL.

Usage:
    .venv/bin/python -m scripts.verify
"""

from __future__ import annotations

import time

from polyfinder import bot_score, features, report
from polyfinder.clients.clob import ClobClient
from polyfinder.clients.data_api import DataApiClient
from polyfinder.clients.gamma import GammaClient
from polyfinder.db import connect, init_db
from polyfinder.discover import by_market
from polyfinder.filters import Filter
from polyfinder.ingest.all import ingest_wallet_full


def step(label: str) -> None:
    print(f"\n=== {label} ===")


def main() -> None:
    init_db()

    step("1) Smoke test all clients")
    with GammaClient() as g:
        m = g.list_markets(limit=1, active=True, closed=False)
    assert m, "Gamma returned no markets"
    cid = m[0]["conditionId"]
    print("Gamma OK; sample cid:", cid[:14], "slug:", m[0].get("slug"))

    with ClobClient() as c:
        token_ids_raw = m[0].get("clobTokenIds")
        import json
        tids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        mid = c.get_midpoint(tids[0])
    assert mid is not None, "CLOB midpoint missing"
    print("CLOB midpoint OK:", mid)

    with DataApiClient() as d:
        trades = d.get_trades(market=cid, limit=5)
    assert trades, f"No trades for market {cid}"
    sample_wallet = trades[0]["proxyWallet"].lower()
    print("data-api OK; sample wallet:", sample_wallet)

    step("2) Round-trip a real wallet")
    summary = ingest_wallet_full(sample_wallet, max_activity=300)
    print("ingest summary:", summary)
    f = features.recompute(sample_wallet)
    assert f, "features missing"
    s = bot_score.recompute(sample_wallet)
    print(f"features OK: n_trades={f['n_trades']} pnl={f['realized_pnl']:.2f} bot_score={s}")

    step("3) Discovery by_market and filter")
    wallets = by_market.by_condition_id(cid, max_trades=500)
    print(f"discovered {len(wallets)} unique wallets on market")
    # ingest a small slice and check filter behavior
    for w in wallets[:5]:
        ingest_wallet_full(w, max_activity=100)
    features.recompute_many(wallets[:5])
    bot_score.recompute_many(wallets[:5])

    f = Filter.in_wallets(wallets[:5]) & Filter.n_trades_min(1)
    rows = f.apply(
        select="wf.wallet, wf.n_trades, wf.realized_pnl, wf.account_age_days, wf.bot_score, wf.dominant_category",
        order_by="wf.realized_pnl DESC",
    )
    report.table(rows, title="Sample wallets in market")

    step("4) Re-run filter (should be sub-second)")
    t0 = time.time()
    n = f.count()
    print(f"count={n} in {(time.time()-t0)*1000:.1f}ms (cached)")

    step("5) DB summary")
    with connect() as c:
        for tbl in ("users", "activities", "markets", "market_tags", "positions",
                    "wallet_features", "wallet_category_stats", "discovery_runs"):
            n = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl}: {n}")

    print("\n=== VERIFY DONE ===")


if __name__ == "__main__":
    main()
