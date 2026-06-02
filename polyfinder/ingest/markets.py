"""Ingest market metadata + resolution status into the markets table.

Polymarket "category" lives on the parent event, not the market. So when we ingest
a market we'll fetch its event for the category + tags.
"""

from __future__ import annotations

import json
import time
from typing import Iterable

from .. import db
from ..clients.gamma import GammaClient


def _parse_iso(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        # Polymarket returns RFC3339 strings like "2026-06-30T00:00:00Z"
        from dateutil import parser as dtp

        return int(dtp.isoparse(ts).timestamp())
    except Exception:
        return None


def _normalize_market(m: dict, event_category: str | None, event_tags: list[str] | None) -> dict:
    """Flatten a Gamma market dict into the `markets` table shape."""
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = None

    token_ids = m.get("clobTokenIds")
    if isinstance(token_ids, str):
        try:
            token_ids = json.loads(token_ids)
        except Exception:
            token_ids = None

    resolved_outcome = None
    if m.get("closed"):
        # Polymarket reports the winning outcome via `outcomePrices` ~= ["1","0"] / ["0","1"]
        op = m.get("outcomePrices")
        if isinstance(op, str):
            try:
                op = json.loads(op)
            except Exception:
                op = None
        if isinstance(op, list) and isinstance(outcomes, list) and len(op) == len(outcomes):
            try:
                idx = max(range(len(op)), key=lambda i: float(op[i] or 0))
                if float(op[idx]) >= 0.99:
                    resolved_outcome = outcomes[idx]
            except Exception:
                pass

    return {
        "condition_id": m.get("conditionId"),
        "market_id": str(m.get("id")) if m.get("id") is not None else None,
        "slug": m.get("slug"),
        "question": m.get("question"),
        "description": m.get("description"),
        "category": event_category or m.get("category"),
        "event_slug": (m.get("events") or [{}])[0].get("slug") if isinstance(m.get("events"), list) else None,
        "outcome_count": len(outcomes) if isinstance(outcomes, list) else None,
        "outcomes_json": json.dumps(outcomes) if outcomes is not None else None,
        "token_ids_json": json.dumps(token_ids) if token_ids is not None else None,
        "created_at": _parse_iso(m.get("createdAt")),
        "end_date": _parse_iso(m.get("endDate") or m.get("endDateIso")),
        "closed": 1 if m.get("closed") else 0,
        "resolved": 1 if (m.get("closed") and resolved_outcome is not None) else 0,
        "resolved_outcome": resolved_outcome,
        "resolution_source": m.get("resolutionSource"),
        "volume_usdc": float(m.get("volumeNum") or m.get("volume") or 0) or None,
        "liquidity_usdc": float(m.get("liquidityNum") or m.get("liquidity") or 0) or None,
        "raw_json": json.dumps(m),
        "last_synced_at": int(time.time()),
    }


def upsert_market(market: dict, *, event_category: str | None = None, event_tags: list[str] | None = None) -> str:
    row = _normalize_market(market, event_category, event_tags)
    cid = row["condition_id"]
    if not cid:
        return ""
    with db.connect() as conn:
        db.upsert(conn, "markets", row, pk=("condition_id",))
        if event_tags:
            for t in event_tags:
                db.upsert(conn, "market_tags", {"condition_id": cid, "tag": t}, pk=("condition_id", "tag"))
    return cid


def upsert_markets(markets: Iterable[dict], *, event_category: str | None = None, event_tags: list[str] | None = None) -> int:
    rows = []
    tag_rows = []
    for m in markets:
        r = _normalize_market(m, event_category, event_tags)
        if r["condition_id"]:
            rows.append(r)
            if event_tags:
                for t in event_tags:
                    tag_rows.append({"condition_id": r["condition_id"], "tag": t})
    if not rows:
        return 0
    with db.connect() as conn:
        n = db.upsert_many(conn, "markets", rows, pk=("condition_id",))
        if tag_rows:
            db.upsert_many(conn, "market_tags", tag_rows, pk=("condition_id", "tag"))
    return n


# Canonical top-level categories — used to pick a primary category from event tags.
CANONICAL_CATEGORIES = [
    "Politics", "Sports", "Crypto", "Pop Culture", "Business", "Tech",
    "Science", "Climate", "Weather", "Geopolitics", "World", "Elections",
    "Health", "Entertainment", "AI",
]


def _pick_category(tag_labels: list[str]) -> str | None:
    """Choose a single canonical 'category' label from an event's tag list."""
    if not tag_labels:
        return None
    s = {t for t in tag_labels}
    for c in CANONICAL_CATEGORIES:
        if c in s:
            return c
    return tag_labels[0]


def _enrich_with_event(g: GammaClient, m: dict) -> tuple[str | None, list[str]]:
    """Fetch the event detail for a market and return (category, tag_labels)."""
    events = m.get("events") or []
    if not events:
        return None, []
    ev_id = events[0].get("id")
    if not ev_id:
        return None, []
    try:
        e = g.get_json(f"/events/{ev_id}")
    except Exception:
        return None, []
    labels: list[str] = []
    for t in e.get("tags") or []:
        label = t.get("label") if isinstance(t, dict) else str(t)
        if label:
            labels.append(label)
    return _pick_category(labels), labels


def fetch_and_store_market_by_slug(slug: str) -> str | None:
    """Look up a market by slug, attach event category/tags, persist, return condition_id."""
    with GammaClient() as g:
        m = g.market_by_slug(slug)
        if not m:
            return None
        cat, tags = _enrich_with_event(g, m)
        return upsert_market(m, event_category=cat, event_tags=tags)


def fetch_and_store_market_by_condition(condition_id: str) -> str | None:
    """Resolve a conditionId -> Gamma market -> persist with event category/tags."""
    with GammaClient() as g:
        rows = g.list_markets(condition_ids=[condition_id], limit=1)
        if not rows:
            return None
        m = rows[0]
        cat, tags = _enrich_with_event(g, m)
        return upsert_market(m, event_category=cat, event_tags=tags)


def ensure_markets(condition_ids: Iterable[str]) -> int:
    """For each condition_id not already in the DB, fetch + persist. Returns count fetched."""
    cids = list({c for c in condition_ids if c})
    if not cids:
        return 0
    with db.connect() as conn:
        existing = {r[0] for r in conn.execute(
            f"SELECT condition_id FROM markets WHERE condition_id IN ({','.join('?'*len(cids))})",
            cids,
        ).fetchall()}
    missing = [c for c in cids if c not in existing]
    fetched = 0
    for cid in missing:
        if fetch_and_store_market_by_condition(cid):
            fetched += 1
    return fetched
