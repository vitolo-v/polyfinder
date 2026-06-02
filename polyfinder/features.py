"""Per-wallet feature computation.

All features are derived from rows already in the SQLite DB. Call:
    features.recompute(wallet)        # one wallet
    features.recompute_many(wallets)  # batch

Outputs land in `wallet_features` and per-category stats in `wallet_category_stats`.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from typing import Iterable

from . import db
from .ingest.users import ensure_user_row


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _hhi(amounts: dict[str, float]) -> float | None:
    total = sum(amounts.values())
    if total <= 0:
        return None
    return sum((v / total) ** 2 for v in amounts.values())


def _round_stake(usdc: float) -> bool:
    """Human-friendly rounded stake: $5/$10/$25/$50/$100/... within 1%."""
    if usdc is None or usdc <= 0:
        return False
    for r in (5, 10, 20, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000):
        if abs(usdc - r) / r < 0.01:
            return True
    return False


def recompute(wallet: str) -> dict | None:
    """Recompute every feature for one wallet from activities + positions + markets."""
    wallet = wallet.lower()
    ensure_user_row(wallet)

    with db.connect() as conn:
        acts = conn.execute(
            """
            SELECT a.ts, a.type, a.side, a.size, a.size_usdc, a.price, a.condition_id,
                   a.token_id, a.outcome, m.category, m.resolved, m.resolved_outcome
            FROM activities a LEFT JOIN markets m USING (condition_id)
            WHERE a.wallet = ? ORDER BY a.ts ASC
            """,
            (wallet,),
        ).fetchall()
        positions = conn.execute(
            "SELECT realized_pnl, unrealized_pnl FROM positions WHERE wallet=?",
            (wallet,),
        ).fetchall()

    if not acts:
        return None

    trades = [a for a in acts if (a["type"] or "").lower() == "trade"]
    splits = [a for a in acts if (a["type"] or "").lower() == "split"]
    merges = [a for a in acts if (a["type"] or "").lower() == "merge"]
    redemptions = [a for a in acts if (a["type"] or "").lower() in ("redemption", "redeem")]

    first_ts = min(a["ts"] for a in acts)
    last_ts = max(a["ts"] for a in acts)
    now = int(time.time())
    age_days = (now - first_ts) / 86400.0

    n_trades = len(trades)
    n_markets = len({a["condition_id"] for a in acts if a["condition_id"]})

    by_market: dict[str, float] = {}
    by_category: dict[str, dict] = {}
    sizes = []
    night_count = 0
    hours_seen: set[int] = set()
    round_count = 0

    # Track per-market net buys (so we can attribute wins/losses on resolved markets).
    # We approximate "won the bet" as: for each (wallet, condition_id), look at net
    # outcome held at close — but we don't have minute-by-minute holdings here without
    # a heavier reconstruction. Instead use positions table (current realized PnL).
    # For win/loss, we use: trades on resolved markets where (price-paid < 1 and outcome won)
    # or shorts where outcome lost. Simpler: did the wallet end up with the winning outcome?

    # Per (condition_id, outcome) net shares bought (buy positive, sell negative).
    net_shares: dict[tuple[str, str], float] = {}

    for a in trades:
        u = a["size_usdc"] or 0.0
        sizes.append(u)
        if a["condition_id"]:
            by_market[a["condition_id"]] = by_market.get(a["condition_id"], 0.0) + u
        cat = a["category"] or "Unknown"
        bc = by_category.setdefault(cat, {"n_trades": 0, "volume": 0.0, "n_wins": 0, "n_losses": 0})
        bc["n_trades"] += 1
        bc["volume"] += u
        # hour bucket
        hour = ((a["ts"] or 0) // 3600) % 24
        hours_seen.add(hour)
        if hour < 6:
            night_count += 1
        if _round_stake(u):
            round_count += 1
        # net shares: buys add, sells subtract
        shares = float(a["size"] or 0.0)
        sign = -1.0 if (a["side"] or "").lower() == "sell" else 1.0
        key = (a["condition_id"] or "", a["outcome"] or "")
        net_shares[key] = net_shares.get(key, 0.0) + sign * shares

    # Win/loss attribution on resolved markets:
    # if net_shares of (cid, outcome) > 0 and outcome == resolved_outcome -> win
    # else if net_shares > 0 and outcome != resolved_outcome -> loss
    resolved_lookup: dict[str, str] = {}
    cid_list = sorted({a["condition_id"] for a in acts if a["condition_id"]})
    if cid_list:
        seq = ",".join("?" * len(cid_list))
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT condition_id, resolved_outcome FROM markets WHERE resolved=1 AND condition_id IN ({seq})",
                cid_list,
            ).fetchall()
        for r in rows:
            if r["resolved_outcome"]:
                resolved_lookup[r["condition_id"]] = r["resolved_outcome"]

    n_wins = n_losses = n_resolved_bets = 0
    for (cid, outcome), shares in net_shares.items():
        if shares <= 0 or cid not in resolved_lookup:
            continue
        n_resolved_bets += 1
        if outcome == resolved_lookup[cid]:
            n_wins += 1
            for cat_d in by_category.values():
                pass  # category wins/losses tracked below
        else:
            n_losses += 1
    # Distribute wins/losses per category (re-loop, simple)
    for (cid, outcome), shares in net_shares.items():
        if shares <= 0 or cid not in resolved_lookup:
            continue
        with db.connect() as conn:
            row = conn.execute("SELECT category FROM markets WHERE condition_id=?", (cid,)).fetchone()
        cat = (row["category"] if row else None) or "Unknown"
        bc = by_category.setdefault(cat, {"n_trades": 0, "volume": 0.0, "n_wins": 0, "n_losses": 0})
        if outcome == resolved_lookup[cid]:
            bc["n_wins"] += 1
        else:
            bc["n_losses"] += 1

    win_rate = (n_wins / n_resolved_bets) if n_resolved_bets > 0 else None

    # inter-trade gaps
    trade_ts = [a["ts"] for a in trades if a["ts"]]
    if len(trade_ts) >= 2:
        gaps = [trade_ts[i + 1] - trade_ts[i] for i in range(len(trade_ts) - 1) if trade_ts[i + 1] >= trade_ts[i]]
        gap_p50 = _percentile(gaps, 50)
        gap_p95 = _percentile(gaps, 95)
        gap_mean = statistics.fmean(gaps)
        gap_std = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
        gap_cv = (gap_std / gap_mean) if gap_mean > 0 else None
    else:
        gap_p50 = gap_p95 = gap_cv = None

    realized_total = sum(p["realized_pnl"] for p in positions if p["realized_pnl"] is not None)
    unrealized_total = sum(p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None)
    total_volume = sum(sizes)

    market_hhi = _hhi(by_market)
    cat_hhi = _hhi({c: d["volume"] for c, d in by_category.items()})
    dominant_cat = max(by_category.items(), key=lambda kv: kv[1]["volume"])[0] if by_category else None

    feat = {
        "wallet": wallet,
        "account_age_days": round(age_days, 3),
        "n_trades": n_trades,
        "n_markets": n_markets,
        "n_categories": len(by_category),
        "realized_pnl": realized_total,
        "unrealized_pnl": unrealized_total,
        "total_volume_usdc": total_volume,
        "avg_trade_usdc": (statistics.fmean(sizes) if sizes else None),
        "median_trade_usdc": (statistics.median(sizes) if sizes else None),
        "win_rate_resolved": win_rate,
        "n_resolved_bets": n_resolved_bets,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "market_concentration_hhi": market_hhi,
        "category_concentration_hhi": cat_hhi,
        "dominant_category": dominant_cat,
        "inter_trade_seconds_p50": gap_p50,
        "inter_trade_seconds_p95": gap_p95,
        "inter_trade_seconds_cv": gap_cv,
        "night_trade_ratio": (night_count / n_trades) if n_trades else None,
        "hours_active_count": len(hours_seen),
        "round_stake_ratio": (round_count / n_trades) if n_trades else None,
        "redemption_count": len(redemptions),
        "split_count": len(splits),
        "merge_count": len(merges),
        "bot_score": None,  # filled later by bot_score.recompute
        "bot_reasons_json": None,
        "computed_at": int(time.time()),
    }

    with db.connect() as conn:
        db.upsert(conn, "wallet_features", feat, pk=("wallet",))
        # category rollup
        # delete existing for this wallet then re-insert
        conn.execute("DELETE FROM wallet_category_stats WHERE wallet=?", (wallet,))
        for cat, d in by_category.items():
            conn.execute(
                """INSERT INTO wallet_category_stats
                       (wallet, category, n_trades, volume_usdc, realized_pnl, n_wins, n_losses)
                   VALUES (?,?,?,?,?,?,?)""",
                (wallet, cat, d["n_trades"], d["volume"], None, d["n_wins"], d["n_losses"]),
            )

    return feat


def recompute_many(wallets: Iterable[str]) -> int:
    n = 0
    for w in wallets:
        try:
            if recompute(w):
                n += 1
        except Exception as e:
            print(f"feature compute failed for {w}: {e}")
    return n
