"""Discover wallets that traded a given market (by slug or conditionId)."""

from __future__ import annotations

from ..clients.data_api import DataApiClient
from ..ingest import activity as activity_ingest
from ..ingest import markets as markets_ingest
from . import record_run


def by_condition_id(
    condition_id: str,
    *,
    max_trades: int | None = None,
    store_trades: bool = True,
) -> list[str]:
    """Return the set of wallets that traded this market.

    If store_trades=True, every trade row is also persisted to `activities`,
    which is useful because downstream filters can then reason about each
    wallet's behavior on this specific market without re-fetching.
    """
    if store_trades:
        activity_ingest.ingest_market_trades(condition_id, max_records=max_trades)
        # Pull condition_id wallets straight from DB after ingest.
        from .. import db
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT wallet FROM activities WHERE condition_id=? ORDER BY wallet",
                (condition_id,),
            ).fetchall()
        wallets = [r[0] for r in rows]
    else:
        wallets_seen: set[str] = set()
        with DataApiClient() as client:
            for t in client.iter_trades(market=condition_id):
                w = (t.get("proxyWallet") or "").lower()
                if w:
                    wallets_seen.add(w)
                if max_trades and len(wallets_seen) >= max_trades:
                    break
        wallets = sorted(wallets_seen)

    # Make sure the market row exists with category/tags.
    markets_ingest.fetch_and_store_market_by_condition(condition_id)
    record_run("by_market.condition", {"condition_id": condition_id, "max_trades": max_trades}, wallets)
    return wallets


def by_slug(slug: str, **kwargs) -> list[str]:
    """Same as by_condition_id but resolves a slug first."""
    cid = markets_ingest.fetch_and_store_market_by_slug(slug)
    if not cid:
        return []
    return by_condition_id(cid, **kwargs)
