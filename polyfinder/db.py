"""SQLite connection + schema bootstrap.

Usage:
    from polyfinder.db import connect, init_db
    init_db()                          # idempotent; creates tables/indexes
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users LIMIT 10").fetchall()
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config


def _connect_raw(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or config.DB_PATH
    config.ensure_dirs()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context-managed connection that commits on success, rolls back on error."""
    conn = _connect_raw(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> Path:
    """Create the schema if it doesn't exist. Idempotent."""
    schema_sql = config.SCHEMA_PATH.read_text()
    with connect(path) as conn:
        conn.executescript(schema_sql)
    return path or config.DB_PATH


def upsert(
    conn: sqlite3.Connection,
    table: str,
    row: dict,
    pk: tuple[str, ...],
) -> None:
    """Generic INSERT ... ON CONFLICT DO UPDATE for any table.

    Args:
        conn: open sqlite connection
        table: table name
        row: column -> value mapping
        pk: tuple of column names that form the conflict target
    """
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    pk_list = ",".join(pk)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in pk)
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_list}) DO UPDATE SET {updates}"
        if updates
        else f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"
    )
    conn.execute(sql, [row[c] for c in cols])


def upsert_many(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict],
    pk: tuple[str, ...],
) -> int:
    """Bulk upsert. Returns number of rows submitted."""
    if not rows:
        return 0
    # All rows must share the same columns; take the union and fill missing with None.
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                cols.append(k)
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    pk_list = ",".join(pk)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in pk)
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_list}) DO UPDATE SET {updates}"
        if updates
        else f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"
    )
    conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    return len(rows)
