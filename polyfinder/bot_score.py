"""Heuristic bot-vs-human score.

Reads `wallet_features` and writes back `bot_score` (0..1) + `bot_reasons_json`.
No ML; transparent weighted signals so the user can see *why* a wallet was flagged.

Signals (each contributes 0..1, weighted):
  - cadence_regularity:    low CV of inter-trade gaps               (bot-like)
  - twentyfour_seven:      many distinct active UTC hours           (bot-like)
  - night_trading:         high fraction of trades in 00:00-06:00   (bot-like)
  - young_high_volume:     account_age < N days but huge trade count
  - micro_stakes:          median stake very small + many trades    (MM bot)
  - low_round_stakes:      bots rarely place exactly-round USDC     (humans do)
  - split_merge_heavy:     ratio of (splits+merges)/trades is high  (arbitrage bot)
  - low_market_concentration: HHI very low → spread thin (MM bot)
"""

from __future__ import annotations

import json
import time
from typing import Iterable

from . import db


WEIGHTS = {
    "cadence_regularity": 0.20,
    "twentyfour_seven": 0.15,
    "night_trading": 0.10,
    "young_high_volume": 0.10,
    "micro_stakes": 0.15,
    "low_round_stakes": 0.10,
    "split_merge_heavy": 0.10,
    "low_market_concentration": 0.10,
}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _score_row(f: dict) -> tuple[float, dict]:
    signals: dict[str, float] = {}

    cv = f.get("inter_trade_seconds_cv")
    if cv is not None and f.get("n_trades", 0) >= 10:
        signals["cadence_regularity"] = _clip(1.0 - cv / 3.0)  # CV<=1 -> strong bot, CV>=3 -> human-ish
    else:
        signals["cadence_regularity"] = 0.0

    hac = f.get("hours_active_count") or 0
    signals["twentyfour_seven"] = _clip((hac - 6) / 18.0) if (f.get("n_trades", 0) >= 20) else 0.0

    nt = f.get("night_trade_ratio") or 0.0
    signals["night_trading"] = _clip((nt - 0.10) / 0.35)

    age = f.get("account_age_days") or 0.0
    n_trades = f.get("n_trades") or 0
    if age > 0 and n_trades > 0:
        trades_per_day = n_trades / max(age, 1.0)
        # >100 trades/day on a wallet <14 days old is very bot-like
        signals["young_high_volume"] = _clip(((30 - age) / 30) * (trades_per_day / 50.0))
    else:
        signals["young_high_volume"] = 0.0

    med = f.get("median_trade_usdc")
    if med is not None and n_trades >= 50:
        # micro-stakes (< $2 median) + lots of trades is strong MM signal
        signals["micro_stakes"] = _clip((5 - med) / 5.0)
    else:
        signals["micro_stakes"] = 0.0

    rsr = f.get("round_stake_ratio")
    if rsr is not None and n_trades >= 20:
        # humans hit round numbers ~20-50% of the time; bots near 0%
        signals["low_round_stakes"] = _clip((0.15 - rsr) / 0.15)
    else:
        signals["low_round_stakes"] = 0.0

    sm = (f.get("split_count") or 0) + (f.get("merge_count") or 0)
    if n_trades > 0:
        signals["split_merge_heavy"] = _clip((sm / n_trades) / 0.3)
    else:
        signals["split_merge_heavy"] = 0.0

    hhi = f.get("market_concentration_hhi")
    n_markets = f.get("n_markets") or 0
    if hhi is not None and n_markets >= 20:
        signals["low_market_concentration"] = _clip((0.05 - hhi) / 0.05)
    else:
        signals["low_market_concentration"] = 0.0

    total = sum(WEIGHTS[k] * signals.get(k, 0.0) for k in WEIGHTS)
    reasons = {k: round(v, 3) for k, v in signals.items() if v > 0.1}
    return round(total, 4), reasons


def recompute(wallet: str) -> float | None:
    wallet = wallet.lower()
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM wallet_features WHERE wallet=?", (wallet,)).fetchone()
        if not r:
            return None
        feat = dict(r)
    score, reasons = _score_row(feat)
    with db.connect() as conn:
        conn.execute(
            "UPDATE wallet_features SET bot_score=?, bot_reasons_json=?, computed_at=? WHERE wallet=?",
            (score, json.dumps(reasons), int(time.time()), wallet),
        )
    return score


def recompute_many(wallets: Iterable[str]) -> int:
    n = 0
    for w in wallets:
        if recompute(w) is not None:
            n += 1
    return n


def recompute_all() -> int:
    with db.connect() as conn:
        wallets = [r[0] for r in conn.execute("SELECT wallet FROM wallet_features").fetchall()]
    return recompute_many(wallets)
