"""CLOB (Central Limit Order Book) API: prices, midpoints, books.

Used for spot/fair-value snapshots when computing PnL or trade analysis.
"""

from __future__ import annotations

from .. import config
from ._http import PolyClient


class ClobClient(PolyClient):
    def __init__(self) -> None:
        super().__init__(config.CLOB_API_URL)

    def get_price(self, token_id: str, side: str = "BUY") -> float | None:
        d = self.get_json("/price", params={"token_id": token_id, "side": side.upper()})
        if isinstance(d, dict) and "price" in d:
            return float(d["price"])
        return None

    def get_midpoint(self, token_id: str) -> float | None:
        d = self.get_json("/midpoint", params={"token_id": token_id})
        if isinstance(d, dict) and "mid" in d:
            return float(d["mid"])
        return None

    def get_book(self, token_id: str) -> dict | None:
        d = self.get_json("/book", params={"token_id": token_id})
        return d if isinstance(d, dict) else None
