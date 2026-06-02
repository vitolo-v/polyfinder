"""Scratchpad for ad-hoc filter/aggregation queries.

This file gets rewritten every time you ask me a specific question. Treat the
contents as ephemeral — the lasting state lives in `polyfinder.db`.

Example session shape:
    1. Discover wallets (some combination of by_market / by_holders / by_seed / by_recent)
    2. Ingest each wallet's full activity & positions
    3. Recompute features + bot scores
    4. Apply a Filter, print a report, optionally export to CSV

The body below is just an example; replace it per question.
"""

from __future__ import annotations

from polyfinder import aggregate, bot_score, features, report
from polyfinder.db import init_db
from polyfinder.discover import by_market
from polyfinder.filters import Filter
from polyfinder.ingest.all import ingest_wallet_full


def main() -> None:
    init_db()

    # --- 1) Discovery -------------------------------------------------------
    # Example: wallets that bet on a specific Bitcoin price market.
    wallets = by_market.by_slug(
        "will-bitcoin-hit-150k-by-june-30-2026",
        max_trades=2000,
    )
    print(f"discovered {len(wallets)} wallets")

    # --- 2) Per-wallet ingest ----------------------------------------------
    for w in wallets[:25]:  # cap for demo
        ingest_wallet_full(w, max_activity=300)

    # --- 3) Features + bot score -------------------------------------------
    features.recompute_many(wallets[:25])
    bot_score.recompute_many(wallets[:25])

    # --- 4) Filter & report ------------------------------------------------
    flt = (
        Filter.in_wallets(wallets[:25])
        & Filter.n_trades_min(10)
        & Filter.realized_pnl_min(-1_000_000)  # no PnL floor; just an example
    )
    print("matching:", flt.count())
    report.table(
        flt.apply(
            select="wf.wallet, wf.n_trades, wf.realized_pnl, wf.account_age_days, wf.bot_score, wf.dominant_category",
            order_by="wf.realized_pnl DESC",
            limit=20,
        ),
        title="Top by PnL",
    )
    report.table(aggregate.count_by_category(flt), title="Category breakdown")


if __name__ == "__main__":
    main()
