"""Full ingest helper: run profile + activity + positions + market metadata for a wallet."""

from __future__ import annotations

from .. import db
from . import activity, markets, positions, users


def ingest_wallet_full(wallet: str, *, refresh_markets: bool = True, max_activity: int | None = None) -> dict:
    """One-call ingestion for a wallet. Returns a small summary dict."""
    wallet = wallet.lower()
    users.upsert_user_profile_from_activity(wallet)
    n_act = activity.ingest_wallet_activity(wallet, max_records=max_activity)
    n_pos = positions.ingest_wallet_positions(wallet)
    n_mkt = 0
    if refresh_markets:
        with db.connect() as conn:
            cids = [r[0] for r in conn.execute(
                "SELECT DISTINCT condition_id FROM activities WHERE wallet=? AND condition_id IS NOT NULL",
                (wallet,),
            ).fetchall()]
        n_mkt = markets.ensure_markets(cids)
    return {"wallet": wallet, "activities": n_act, "positions": n_pos, "new_markets": n_mkt}
