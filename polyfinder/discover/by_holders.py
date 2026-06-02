"""Discover wallets that are top current holders of a market's outcome tokens."""

from __future__ import annotations

from ..clients.data_api import DataApiClient
from ..ingest import markets as markets_ingest
from . import record_run


def by_condition_id(condition_id: str, *, limit: int = 200, outcome_index: int | None = None) -> list[str]:
    """Top holders of each outcome (or one specific outcome) of a market.

    Returns wallets uniquely sorted by raw holder amount (largest first across
    both outcomes if no outcome_index is given).
    """
    markets_ingest.fetch_and_store_market_by_condition(condition_id)
    with DataApiClient() as client:
        groups = client.get_holders(condition_id, limit=limit)

    rows: list[tuple[str, float]] = []
    for grp in groups:
        if outcome_index is not None:
            # groups are ordered by outcome index in Polymarket's response
            if groups.index(grp) != outcome_index:
                continue
        for h in grp.get("holders") or []:
            w = (h.get("proxyWallet") or "").lower()
            if w:
                rows.append((w, float(h.get("amount") or 0)))
    # uniquify keeping max amount
    by_wallet: dict[str, float] = {}
    for w, amt in rows:
        if amt > by_wallet.get(w, 0):
            by_wallet[w] = amt
    wallets = [w for w, _ in sorted(by_wallet.items(), key=lambda kv: kv[1], reverse=True)]
    record_run(
        "by_holders",
        {"condition_id": condition_id, "limit": limit, "outcome_index": outcome_index},
        wallets,
    )
    return wallets
