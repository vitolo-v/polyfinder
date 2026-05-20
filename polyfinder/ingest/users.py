"""User profile metadata ingest (username, bio, image) — sourced from activity rows.

Polymarket doesn't expose a standalone profile-by-wallet endpoint, but every trade /
activity row carries the trader's pseudonym + bio + profileImage. We piggyback on
those to fill the `users` table.
"""

from __future__ import annotations

import time

from .. import db
from ..clients.data_api import DataApiClient


def upsert_user_profile_from_activity(wallet: str) -> None:
    """Hit /activity for one row to extract profile fields, then upsert into users."""
    wallet = wallet.lower()
    with DataApiClient() as client:
        rows = client.get_activity(wallet, limit=1)
    if not rows:
        return
    r = rows[0]
    profile = {
        "wallet": wallet,
        "username": r.get("name"),
        "display_name": r.get("pseudonym"),
        "bio": r.get("bio"),
        "profile_image": r.get("profileImage") or r.get("profileImageOptimized"),
        "last_synced_at": int(time.time()),
    }
    profile = {k: v for k, v in profile.items() if v is not None or k == "wallet"}
    with db.connect() as conn:
        existing = conn.execute("SELECT wallet FROM users WHERE wallet=?", (wallet,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO users (wallet, last_synced_at) VALUES (?, ?)", (wallet, int(time.time())))
        cols = [c for c in profile if c != "wallet"]
        if cols:
            sets = ",".join(f"{c}=?" for c in cols)
            conn.execute(f"UPDATE users SET {sets} WHERE wallet=?", [profile[c] for c in cols] + [wallet])


def ensure_user_row(wallet: str) -> None:
    """Insert an empty users row if missing — used by features.recompute before write."""
    wallet = wallet.lower()
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (wallet, last_synced_at) VALUES (?, ?)",
            (wallet, int(time.time())),
        )
