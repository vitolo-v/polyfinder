"""Discover wallets active in a recent window across markets.

Strategy: pick top-volume markets within a window via Gamma, then for each
market scrape /trades and collect unique proxyWallets. This is the workhorse
for "find me wallets who traded in the last 7 days in Crypto markets".

For longer historical windows or full coverage, use discover.by_subgraph
(when the Goldsky URLs are configured).
"""

from __future__ import annotations

import time

from ..clients.data_api import DataApiClient
from ..clients.gamma import GammaClient
from ..ingest import activity as activity_ingest
from ..ingest import markets as markets_ingest
from . import record_run


def _matches_category_or_tag(market_meta: dict, want_category: str | None, want_tag: str | None) -> bool:
    if not want_category and not want_tag:
        return True
    # market_meta is the Gamma /markets row, with nested `events[0]` carrying basic fields.
    # We rely on the previously-cached `markets` row to filter; if missing, ingest first.
    return True  # Filtering by category is applied later via DB join.


def by_window(
    *,
    start_ts: int,
    end_ts: int | None = None,
    category: str | None = None,
    tag: str | None = None,
    market_limit: int = 200,
    per_market_trade_limit: int = 1000,
    only_closed: bool | None = None,
) -> list[str]:
    """Discover wallets that traded any market falling in [start_ts, end_ts].

    Approach:
      1. List markets via Gamma whose end_date/start_date overlaps the window
         (we approximate via the `order=volumeNum` + endDate filter).
      2. Filter by category/tag using the markets table (after ensuring metadata).
      3. For each market, ingest trades in the window via data-api `/trades`,
         which automatically populates `activities`.
      4. Return DISTINCT wallets active in [start_ts, end_ts] from `activities`.
    """
    end_ts = end_ts or int(time.time())
    selected_cids: list[str] = []

    with GammaClient() as g:
        # Use the events listing because tags are easier to filter there.
        for ev in g.iter_events(page_size=100, closed=only_closed, order="volume1mo", ascending=False):
            tags = [(t.get("label") if isinstance(t, dict) else str(t)) for t in (ev.get("tags") or [])]
            if tag and tag not in tags:
                continue
            if category:
                cat = None
                for c in markets_ingest.CANONICAL_CATEGORIES:
                    if c in tags:
                        cat = c
                        break
                if (cat or (tags[0] if tags else None)) != category:
                    continue
            # Walk the event's markets
            mks = ev.get("markets") or []
            for m in mks:
                cid = m.get("conditionId")
                if not cid:
                    continue
                # Quick window check by createdAt / endDate strings on the market
                from dateutil import parser as dtp
                try:
                    created = int(dtp.isoparse(m["createdAt"]).timestamp()) if m.get("createdAt") else None
                    end = int(dtp.isoparse(m["endDate"]).timestamp()) if m.get("endDate") else None
                except Exception:
                    created, end = None, None
                # market overlaps window if it was active at any point inside it
                overlaps = True
                if created and created > end_ts:
                    overlaps = False
                if end and end < start_ts:
                    overlaps = False
                if not overlaps:
                    continue
                selected_cids.append(cid)
            if len(selected_cids) >= market_limit:
                break

    selected_cids = selected_cids[:market_limit]
    # Persist these markets so downstream filters can join on category/tags.
    markets_ingest.ensure_markets(selected_cids)

    # Pull trades for each selected market and stuff them into activities.
    for cid in selected_cids:
        activity_ingest.ingest_market_trades(cid, max_records=per_market_trade_limit)

    # Return wallets active within the window in the DB
    from .. import db
    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT a.wallet
            FROM activities a
            JOIN markets m USING (condition_id)
            WHERE a.ts BETWEEN ? AND ?
              { 'AND m.category = ?' if category else '' }
              { '' }
            ORDER BY a.wallet
            """,
            ([start_ts, end_ts, category] if category else [start_ts, end_ts]),
        ).fetchall()
    wallets = [r[0] for r in rows]

    if tag:
        # Filter wallets to those who traded a market that has the tag.
        with db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT a.wallet
                FROM activities a
                JOIN market_tags mt ON mt.condition_id = a.condition_id
                WHERE mt.tag = ? AND a.ts BETWEEN ? AND ?
                """,
                (tag, start_ts, end_ts),
            ).fetchall()
        wallets = [r[0] for r in rows]

    record_run(
        "by_recent",
        {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "category": category,
            "tag": tag,
            "market_limit": market_limit,
            "per_market_trade_limit": per_market_trade_limit,
            "n_markets_scanned": len(selected_cids),
        },
        wallets,
    )
    return wallets
