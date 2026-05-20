"""Expand a seed wallet to its co-traders (people who trade the same markets within Δt)."""

from __future__ import annotations

from .. import db
from . import record_run


def co_traders(wallet: str, *, window_seconds: int = 600, min_shared_markets: int = 2) -> list[str]:
    """Wallets that traded the same condition_id as `wallet` within `window_seconds`,
    in at least `min_shared_markets` different markets.

    Requires that both the seed wallet AND candidate wallets already have activity
    rows in the DB. Use `ingest.ingest_wallet_full` on the seed first, and ingest
    market trades for the relevant markets to populate candidates.
    """
    wallet = wallet.lower()
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT a2.wallet AS w, COUNT(DISTINCT a1.condition_id) AS shared
            FROM activities a1
            JOIN activities a2
              ON a1.condition_id = a2.condition_id
             AND a2.wallet != a1.wallet
             AND ABS(a1.ts - a2.ts) <= ?
            WHERE a1.wallet = ?
            GROUP BY a2.wallet
            HAVING shared >= ?
            ORDER BY shared DESC
            """,
            (window_seconds, wallet, min_shared_markets),
        ).fetchall()
    wallets = [r["w"] for r in rows]
    record_run(
        "expand.co_traders",
        {"seed": wallet, "window_seconds": window_seconds, "min_shared_markets": min_shared_markets},
        wallets,
    )
    return wallets
