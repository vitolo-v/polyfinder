"""Discovery from a user-supplied wallet list."""

from __future__ import annotations

import re

from . import record_run

_HEX_ADDR = re.compile(r"0x[a-fA-F0-9]{40}")


def from_text(blob: str) -> list[str]:
    """Extract every 0x… wallet from a free-form text blob, normalize, dedupe."""
    found = sorted({m.group(0).lower() for m in _HEX_ADDR.finditer(blob or "")})
    record_run("by_seed.text", {"count": len(found)}, found)
    return found


def from_list(wallets: list[str]) -> list[str]:
    out = sorted({(w or "").lower() for w in wallets if _HEX_ADDR.fullmatch(w or "")})
    record_run("by_seed.list", {"count": len(out)}, out)
    return out
