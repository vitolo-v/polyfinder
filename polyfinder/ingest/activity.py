"""Ingest a wallet's activity feed (trades / splits / merges / redemptions / rewards)."""

from __future__ import annotations

import json
import time

from .. import db
from ..clients.data_api import DataApiClient


def _activity_id(a: dict) -> str:
    """Stable PK from transaction_hash + asset (token) + type + timestamp."""
    tx = a.get("transactionHash") or ""
    asset = a.get("asset") or ""
    typ = a.get("type") or ""
    ts = a.get("timestamp") or 0
    return f"{tx}:{asset}:{typ}:{ts}"


def _normalize_activity(a: dict) -> dict:
    typ = (a.get("type") or "").lower()
    return {
        "id": _activity_id(a),
        "wallet": (a.get("proxyWallet") or "").lower(),
        "type": typ,
        "side": (a.get("side") or "").lower() or None,
        "market_id": str(a.get("marketId")) if a.get("marketId") is not None else None,
        "condition_id": a.get("conditionId"),
        "outcome": a.get("outcome"),
        "token_id": a.get("asset"),
        "size": float(a["size"]) if a.get("size") is not None else None,
        "price": float(a["price"]) if a.get("price") is not None else None,
        "size_usdc": float(a["usdcSize"]) if a.get("usdcSize") is not None else None,
        "ts": int(a["timestamp"]) if a.get("timestamp") is not None else None,
        "tx_hash": a.get("transactionHash"),
        "raw_json": json.dumps(a),
    }


def ingest_wallet_activity(wallet: str, *, page_size: int = 500, max_records: int | None = None) -> int:
    """Pull full activity for a wallet, upsert into DB, return count ingested."""
    wallet = wallet.lower()
    n = 0
    rows: list[dict] = []
    with DataApiClient() as client:
        for a in client.iter_activity(wallet, page_size=page_size):
            row = _normalize_activity(a)
            if not row["ts"]:
                continue
            rows.append(row)
            n += 1
            if max_records and n >= max_records:
                break
            if len(rows) >= 1000:
                _flush(rows)
                rows = []
    if rows:
        _flush(rows)

    # Refresh derived counters on users
    _refresh_user_summary(wallet)
    return n


def _flush(rows: list[dict]) -> None:
    with db.connect() as conn:
        db.upsert_many(conn, "activities", rows, pk=("id",))


def _refresh_user_summary(wallet: str) -> None:
    """Update users.first_trade_at / last_trade_at / n_trades from activities."""
    now = int(time.time())
    with db.connect() as conn:
        r = conn.execute(
            """
            SELECT
              MIN(ts) AS first_ts,
              MAX(ts) AS last_ts,
              SUM(CASE WHEN type='trade' THEN 1 ELSE 0 END) AS n_trades,
              COUNT(DISTINCT condition_id) AS n_markets,
              SUM(CASE WHEN type='trade' THEN size_usdc ELSE 0 END) AS volume
            FROM activities WHERE wallet = ?
            """,
            (wallet,),
        ).fetchone()
        first_ts, last_ts, n_trades, n_markets, volume = (
            r["first_ts"], r["last_ts"], r["n_trades"] or 0, r["n_markets"] or 0, r["volume"] or 0.0,
        )
        # users may not exist yet — create skeleton.
        existing = conn.execute("SELECT wallet FROM users WHERE wallet = ?", (wallet,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE users SET first_trade_at=?, last_trade_at=?, n_trades=?, n_markets=?,
                   volume_usdc=?, created_at_estimate=COALESCE(created_at_estimate, ?), last_synced_at=?
                   WHERE wallet=?""",
                (first_ts, last_ts, n_trades, n_markets, volume, first_ts, now, wallet),
            )
        else:
            conn.execute(
                """INSERT INTO users (wallet, first_trade_at, last_trade_at, n_trades, n_markets,
                       volume_usdc, created_at_estimate, last_synced_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (wallet, first_ts, last_ts, n_trades, n_markets, volume, first_ts, now),
            )


def ingest_market_trades(condition_id: str, *, page_size: int = 500, max_records: int | None = None) -> int:
    """Pull every trade on a market and upsert as activity rows.

    This is the workhorse for `discover.by_market`: after running this you can
    `SELECT DISTINCT wallet FROM activities WHERE condition_id = ?` to get participants.
    """
    n = 0
    rows: list[dict] = []
    with DataApiClient() as client:
        for t in client.iter_trades(market=condition_id, page_size=page_size):
            # /trades rows don't carry a `type`; they're all trades. Add it.
            t["type"] = "TRADE"
            row = _normalize_activity(t)
            if not row["ts"]:
                continue
            rows.append(row)
            n += 1
            if max_records and n >= max_records:
                break
            if len(rows) >= 1000:
                _flush(rows)
                rows = []
    if rows:
        _flush(rows)
    return n
