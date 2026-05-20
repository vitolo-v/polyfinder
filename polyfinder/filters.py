"""Composable filter primitives.

A `Filter` carries a SQL fragment + parameters. You combine them with `&` / `|` / `~`
and call `apply()` to get back a list of wallets matching every condition.

Joins are kept minimal:
  - All filters bind against the `wallet_features wf` table by default.
  - Filters that reference activities/markets add their own subquery.
  - You can pass any extra raw WHERE via `Filter("...sql...", [params])`.

Example:
    f = (
        Filter.created_after("2026-01-01")
        & Filter.n_trades_min(50)
        & Filter.realized_pnl_min(1000)
        & Filter.traded_category("Politics")
        & Filter.won_on_market(slug="will-xyz-happen-2026")
    )
    wallets = f.apply()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from . import db


def _to_ts(s: str | int | datetime) -> int:
    if isinstance(s, int):
        return s
    if isinstance(s, datetime):
        return int(s.timestamp())
    from dateutil import parser as dtp

    dt = dtp.parse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@dataclass
class Filter:
    """A SQL WHERE fragment over `wallet_features wf`.

    The fragment may reference `wf.<col>` directly or use `EXISTS (...)` subqueries
    against `activities a` / `markets m` / `market_tags mt`.
    """

    sql: str
    params: list = field(default_factory=list)

    # --- composition ---------------------------------------------------------

    def __and__(self, other: "Filter") -> "Filter":
        return Filter(f"({self.sql}) AND ({other.sql})", self.params + other.params)

    def __or__(self, other: "Filter") -> "Filter":
        return Filter(f"({self.sql}) OR ({other.sql})", self.params + other.params)

    def __invert__(self) -> "Filter":
        return Filter(f"NOT ({self.sql})", list(self.params))

    # --- materialize ---------------------------------------------------------

    def apply(
        self,
        *,
        order_by: str = "wf.realized_pnl DESC",
        limit: int | None = None,
        offset: int = 0,
        select: str = "wf.wallet",
    ) -> list[dict]:
        sql = (
            f"SELECT {select} FROM wallet_features wf "
            f"WHERE {self.sql} ORDER BY {order_by}"
        )
        params: list = list(self.params)
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        with db.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count(self) -> int:
        sql = f"SELECT COUNT(*) FROM wallet_features wf WHERE {self.sql}"
        with db.connect() as conn:
            return conn.execute(sql, self.params).fetchone()[0]

    # --- factories: account-level -------------------------------------------

    @classmethod
    def created_after(cls, when: str | int | datetime) -> "Filter":
        return cls(
            "EXISTS (SELECT 1 FROM users u WHERE u.wallet=wf.wallet AND u.created_at_estimate >= ?)",
            [_to_ts(when)],
        )

    @classmethod
    def created_before(cls, when: str | int | datetime) -> "Filter":
        return cls(
            "EXISTS (SELECT 1 FROM users u WHERE u.wallet=wf.wallet AND u.created_at_estimate <= ?)",
            [_to_ts(when)],
        )

    @classmethod
    def created_between(cls, start, end) -> "Filter":
        return cls.created_after(start) & cls.created_before(end)

    @classmethod
    def account_age_days_min(cls, days: float) -> "Filter":
        return cls("wf.account_age_days >= ?", [float(days)])

    @classmethod
    def account_age_days_max(cls, days: float) -> "Filter":
        return cls("wf.account_age_days <= ?", [float(days)])

    # --- factories: activity stats ------------------------------------------

    @classmethod
    def n_trades_between(cls, lo: int | None = None, hi: int | None = None) -> "Filter":
        parts: list[str] = []
        params: list = []
        if lo is not None:
            parts.append("wf.n_trades >= ?")
            params.append(lo)
        if hi is not None:
            parts.append("wf.n_trades <= ?")
            params.append(hi)
        return cls(" AND ".join(parts) or "1=1", params)

    @classmethod
    def n_trades_min(cls, lo: int) -> "Filter":
        return cls.n_trades_between(lo=lo)

    @classmethod
    def n_markets_min(cls, lo: int) -> "Filter":
        return cls("wf.n_markets >= ?", [lo])

    @classmethod
    def volume_between(cls, lo: float | None = None, hi: float | None = None) -> "Filter":
        parts, params = [], []
        if lo is not None:
            parts.append("wf.total_volume_usdc >= ?")
            params.append(lo)
        if hi is not None:
            parts.append("wf.total_volume_usdc <= ?")
            params.append(hi)
        return cls(" AND ".join(parts) or "1=1", params)

    # --- factories: PnL -----------------------------------------------------

    @classmethod
    def realized_pnl_between(cls, lo: float | None = None, hi: float | None = None) -> "Filter":
        parts, params = [], []
        if lo is not None:
            parts.append("wf.realized_pnl >= ?")
            params.append(lo)
        if hi is not None:
            parts.append("wf.realized_pnl <= ?")
            params.append(hi)
        return cls(" AND ".join(parts) or "1=1", params)

    @classmethod
    def realized_pnl_min(cls, x: float) -> "Filter":
        return cls.realized_pnl_between(lo=x)

    @classmethod
    def win_rate_min(cls, x: float, *, min_resolved: int = 5) -> "Filter":
        return cls(
            "wf.n_resolved_bets >= ? AND wf.win_rate_resolved >= ?",
            [min_resolved, x],
        )

    # --- factories: time-window activity (uses `activities`) -----------------

    @classmethod
    def traded_in_window(cls, start, end, *, min_trades: int = 1) -> "Filter":
        return cls(
            """EXISTS (
                 SELECT 1 FROM activities a
                 WHERE a.wallet = wf.wallet
                   AND a.type='trade'
                   AND a.ts BETWEEN ? AND ?
                 GROUP BY a.wallet
                 HAVING COUNT(*) >= ?
               )""",
            [_to_ts(start), _to_ts(end), min_trades],
        )

    # --- factories: markets / categories / tags / resolution -----------------

    @classmethod
    def traded_market(cls, *, slug: str | None = None, condition_id: str | None = None) -> "Filter":
        if not slug and not condition_id:
            raise ValueError("Specify slug or condition_id")
        if condition_id:
            return cls(
                "EXISTS (SELECT 1 FROM activities a WHERE a.wallet=wf.wallet AND a.condition_id=?)",
                [condition_id],
            )
        return cls(
            """EXISTS (
                 SELECT 1 FROM activities a JOIN markets m USING (condition_id)
                 WHERE a.wallet=wf.wallet AND m.slug=?
               )""",
            [slug],
        )

    @classmethod
    def traded_category(cls, category: str, *, min_trades: int = 1) -> "Filter":
        return cls(
            """EXISTS (
                 SELECT 1 FROM activities a JOIN markets m USING (condition_id)
                 WHERE a.wallet=wf.wallet AND m.category=? AND a.type='trade'
                 GROUP BY a.wallet HAVING COUNT(*) >= ?
               )""",
            [category, min_trades],
        )

    @classmethod
    def traded_tag(cls, tag: str, *, min_trades: int = 1) -> "Filter":
        return cls(
            """EXISTS (
                 SELECT 1 FROM activities a
                 JOIN market_tags mt ON mt.condition_id = a.condition_id
                 WHERE a.wallet=wf.wallet AND mt.tag=? AND a.type='trade'
                 GROUP BY a.wallet HAVING COUNT(*) >= ?
               )""",
            [tag, min_trades],
        )

    @classmethod
    def dominant_category(cls, category: str) -> "Filter":
        return cls("wf.dominant_category = ?", [category])

    @classmethod
    def category_share_min(cls, category: str, share: float) -> "Filter":
        """Wallet has at least `share` of its volume in `category`."""
        return cls(
            """EXISTS (
                 SELECT 1 FROM wallet_category_stats wcs
                 WHERE wcs.wallet = wf.wallet AND wcs.category = ?
                   AND wcs.volume_usdc / NULLIF(wf.total_volume_usdc, 0) >= ?
               )""",
            [category, float(share)],
        )

    @classmethod
    def won_on_market(cls, *, slug: str | None = None, condition_id: str | None = None) -> "Filter":
        """Wallet had a net-long position on the winning outcome of a resolved market."""
        base = """
            SELECT 1 FROM activities a
            JOIN markets m ON m.condition_id = a.condition_id
            WHERE a.wallet = wf.wallet
              AND a.type='trade'
              AND m.resolved = 1
              AND a.outcome = m.resolved_outcome
              {extra}
            GROUP BY a.wallet, a.condition_id, a.outcome
            HAVING SUM(CASE WHEN a.side='buy' THEN a.size ELSE -a.size END) > 0
        """
        if condition_id:
            return cls(f"EXISTS ({base.format(extra='AND a.condition_id=?')})", [condition_id])
        if slug:
            return cls(f"EXISTS ({base.format(extra='AND m.slug=?')})", [slug])
        return cls(f"EXISTS ({base.format(extra='')})", [])

    @classmethod
    def lost_on_market(cls, *, slug: str | None = None, condition_id: str | None = None) -> "Filter":
        base = """
            SELECT 1 FROM activities a
            JOIN markets m ON m.condition_id = a.condition_id
            WHERE a.wallet = wf.wallet
              AND a.type='trade'
              AND m.resolved = 1
              AND a.outcome <> m.resolved_outcome
              {extra}
            GROUP BY a.wallet, a.condition_id, a.outcome
            HAVING SUM(CASE WHEN a.side='buy' THEN a.size ELSE -a.size END) > 0
        """
        if condition_id:
            return cls(f"EXISTS ({base.format(extra='AND a.condition_id=?')})", [condition_id])
        if slug:
            return cls(f"EXISTS ({base.format(extra='AND m.slug=?')})", [slug])
        return cls(f"EXISTS ({base.format(extra='')})", [])

    # --- factories: bot score ------------------------------------------------

    @classmethod
    def bot_score_min(cls, x: float) -> "Filter":
        return cls("COALESCE(wf.bot_score, 0) >= ?", [float(x)])

    @classmethod
    def bot_score_max(cls, x: float) -> "Filter":
        return cls("COALESCE(wf.bot_score, 0) <= ?", [float(x)])

    @classmethod
    def likely_bot(cls) -> "Filter":
        return cls.bot_score_min(0.55)

    @classmethod
    def likely_human(cls) -> "Filter":
        return cls.bot_score_max(0.30)

    # --- factories: scope to a wallet pool ----------------------------------

    @classmethod
    def in_wallets(cls, wallets: Sequence[str]) -> "Filter":
        wl = [w.lower() for w in wallets]
        if not wl:
            return cls("1=0", [])
        placeholders = ",".join("?" * len(wl))
        return cls(f"wf.wallet IN ({placeholders})", list(wl))

    @classmethod
    def in_discovery_run(cls, run_id: int) -> "Filter":
        return cls(
            "wf.wallet IN (SELECT wallet FROM discovery_wallets WHERE run_id=?)",
            [int(run_id)],
        )

    # --- raw escape hatch ----------------------------------------------------

    @classmethod
    def raw(cls, sql: str, params: Sequence | None = None) -> "Filter":
        return cls(sql, list(params or []))
