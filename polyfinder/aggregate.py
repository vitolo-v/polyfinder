"""Aggregation helpers over filter results.

Designed to be called from chat for "of the N wallets that match X, give me a
breakdown by ___" questions.
"""

from __future__ import annotations

from typing import Sequence

from . import db
from .filters import Filter


def count_by_category(filt: Filter) -> list[dict]:
    """For each canonical category, how many wallets in the filter traded it."""
    sql = f"""
        SELECT m.category AS category,
               COUNT(DISTINCT a.wallet) AS n_wallets,
               SUM(a.size_usdc) AS volume_usdc,
               COUNT(*) AS n_trades
        FROM activities a JOIN markets m USING (condition_id)
        WHERE a.type='trade'
          AND a.wallet IN (
              SELECT wf.wallet FROM wallet_features wf WHERE {filt.sql}
          )
        GROUP BY m.category
        ORDER BY n_wallets DESC
    """
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, filt.params).fetchall()]


def histogram(filt: Filter, *, column: str, bins: list[float], select_table: str = "wallet_features") -> list[dict]:
    """Bucket a numeric column into [bins] and count wallets per bucket.

    bins = [0, 100, 1000, 10000] -> buckets (-inf,0], (0,100], (100,1000], (1000,10000], (10000,inf).
    """
    # Build CASE expression
    cases = []
    labels = []
    prev = "-inf"
    for b in bins:
        cases.append(f"WHEN x <= {b} THEN '({prev}, {b}]'")
        labels.append(f"({prev}, {b}]")
        prev = str(b)
    cases.append(f"ELSE '({prev}, +inf)'")
    labels.append(f"({prev}, +inf)")
    case_expr = "CASE " + " ".join(cases) + " END"

    sql = f"""
        WITH base AS (
          SELECT {column} AS x FROM {select_table} wf WHERE {filt.sql}
        )
        SELECT {case_expr} AS bucket, COUNT(*) AS n
        FROM base
        GROUP BY bucket
    """
    with db.connect() as conn:
        rows = {r["bucket"]: r["n"] for r in conn.execute(sql, filt.params).fetchall()}
    return [{"bucket": lbl, "n": rows.get(lbl, 0)} for lbl in labels]


def summary(filt: Filter) -> dict:
    """Top-line stats for a filter result."""
    sql = f"""
        SELECT
          COUNT(*) AS n_wallets,
          AVG(wf.realized_pnl) AS avg_realized_pnl,
          SUM(wf.realized_pnl) AS sum_realized_pnl,
          AVG(wf.n_trades) AS avg_trades,
          AVG(wf.account_age_days) AS avg_age_days,
          AVG(wf.bot_score) AS avg_bot_score,
          SUM(CASE WHEN wf.bot_score >= 0.55 THEN 1 ELSE 0 END) AS n_likely_bots,
          SUM(CASE WHEN wf.bot_score <= 0.30 THEN 1 ELSE 0 END) AS n_likely_humans
        FROM wallet_features wf WHERE {filt.sql}
    """
    with db.connect() as conn:
        r = conn.execute(sql, filt.params).fetchone()
    return dict(r) if r else {}


def group_by_dominant_category(filt: Filter) -> list[dict]:
    sql = f"""
        SELECT wf.dominant_category AS category,
               COUNT(*) AS n_wallets,
               AVG(wf.realized_pnl) AS avg_pnl,
               AVG(wf.bot_score) AS avg_bot_score
        FROM wallet_features wf WHERE {filt.sql}
        GROUP BY wf.dominant_category ORDER BY n_wallets DESC
    """
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, filt.params).fetchall()]


def top_markets_for(filt: Filter, *, limit: int = 20) -> list[dict]:
    """Most-traded markets among wallets in the filter."""
    sql = f"""
        SELECT m.slug, m.question, m.category,
               COUNT(DISTINCT a.wallet) AS n_wallets,
               SUM(a.size_usdc) AS volume_usdc,
               COUNT(*) AS n_trades
        FROM activities a JOIN markets m USING (condition_id)
        WHERE a.type='trade'
          AND a.wallet IN (SELECT wf.wallet FROM wallet_features wf WHERE {filt.sql})
        GROUP BY m.condition_id
        ORDER BY n_wallets DESC, volume_usdc DESC
        LIMIT ?
    """
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, [*filt.params, limit]).fetchall()]
