"""Pretty-printing helpers for chat output and file exports."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.table import Table

from . import config

_console = Console(record=True)


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        if abs(v) >= 1:
            return f"{v:,.2f}"
        return f"{v:.4f}"
    if isinstance(v, int) and v > 9_999_999_999:  # looks like a unix ts
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return str(v)
    return str(v)


def table(rows: Iterable[dict], *, title: str | None = None, cols: list[str] | None = None) -> str:
    rows = list(rows)
    if not rows:
        msg = f"(no rows){' — ' + title if title else ''}"
        print(msg)
        return msg
    cols = cols or list(rows[0].keys())
    t = Table(title=title, show_lines=False)
    for c in cols:
        t.add_column(c, overflow="fold")
    for r in rows:
        t.add_row(*[_fmt(r.get(c)) for c in cols])
    _console.print(t)
    return _console.export_text(clear=True)


def to_csv(rows: Iterable[dict], filename: str) -> Path:
    rows = list(rows)
    config.ensure_dirs()
    path = config.EXPORT_DIR / filename
    if not rows:
        path.write_text("")
        return path
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    return path


def to_json(rows: Iterable[dict], filename: str) -> Path:
    config.ensure_dirs()
    path = config.EXPORT_DIR / filename
    path.write_text(json.dumps(list(rows), default=str, indent=2))
    return path
