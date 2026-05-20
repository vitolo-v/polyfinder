"""Ingest a wallet's current open positions."""

from __future__ import annotations

import json
import time

from .. import db
from ..clients.data_api import DataApiClient


def _normalize_position(p: dict, wallet: str) -> dict:
    return {
        "wallet": wallet,
        "condition_id": p.get("conditionId"),
        "token_id": p.get("asset") or "",
        "outcome": p.get("outcome"),
        "size": float(p["size"]) if p.get("size") is not None else None,
        "avg_price": float(p["avgPrice"]) if p.get("avgPrice") is not None else None,
        "current_price": float(p["curPrice"]) if p.get("curPrice") is not None else None,
        "current_value": float(p["currentValue"]) if p.get("currentValue") is not None else None,
        "realized_pnl": float(p["realizedPnl"]) if p.get("realizedPnl") is not None else None,
        "unrealized_pnl": float(p["cashPnl"]) if p.get("cashPnl") is not None else None,
        "last_synced_at": int(time.time()),
        "raw_json": json.dumps(p),
    }


def ingest_wallet_positions(wallet: str, *, size_threshold: float | None = 0.0) -> int:
    wallet = wallet.lower()
    rows: list[dict] = []
    with DataApiClient() as client:
        for p in client.iter_positions(wallet, size_threshold=size_threshold):
            row = _normalize_position(p, wallet)
            if row["token_id"]:
                rows.append(row)
    if not rows:
        return 0
    with db.connect() as conn:
        n = db.upsert_many(conn, "positions", rows, pk=("wallet", "token_id"))
        # Update users.unrealized_pnl & realized_pnl from positions roll-up
        r = conn.execute(
            "SELECT SUM(COALESCE(realized_pnl,0)) AS rp, SUM(COALESCE(unrealized_pnl,0)) AS up FROM positions WHERE wallet=?",
            (wallet,),
        ).fetchone()
        conn.execute(
            "UPDATE users SET realized_pnl = COALESCE(?, realized_pnl), unrealized_pnl = COALESCE(?, unrealized_pnl), last_synced_at=? WHERE wallet=?",
            (r["rp"], r["up"], int(time.time()), wallet),
        )
        # if user row didn't exist yet, insert a skeleton
        if conn.total_changes == 0:
            pass  # users row will be created by activity ingest; positions alone are rare
    return n
