"""Discovery primitives: produce lists of wallets seeded from various entry points."""

from __future__ import annotations

import json
import time

from .. import db


def record_run(strategy: str, params: dict, wallets: list[str]) -> int:
    """Log a discovery run and the wallet set it produced. Returns run id."""
    wallets = [w.lower() for w in wallets if w]
    now = int(time.time())
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO discovery_runs (strategy, params_json, n_wallets, ran_at) VALUES (?,?,?,?)",
            (strategy, json.dumps(params, default=str), len(wallets), now),
        )
        run_id = cur.lastrowid
        if wallets:
            conn.executemany(
                "INSERT OR IGNORE INTO discovery_wallets (run_id, wallet) VALUES (?, ?)",
                [(run_id, w) for w in wallets],
            )
    return run_id
