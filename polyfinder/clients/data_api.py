"""data-api.polymarket.com: user activity, positions, trades, value, holders.

All endpoints are public (no auth needed) and paginated by `limit`/`offset`.
"""

from __future__ import annotations

from typing import Iterator

from .. import config
from ._http import PolyClient


class DataApiClient(PolyClient):
    def __init__(self) -> None:
        super().__init__(config.DATA_API_URL)

    # ---- per-wallet feeds ---------------------------------------------------

    def get_activity(
        self,
        wallet: str,
        *,
        limit: int = 100,
        offset: int = 0,
        market: str | None = None,
        type_: str | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> list[dict]:
        """Activity (trades, splits, merges, redemptions, rewards, yields)."""
        params: dict = {"user": wallet, "limit": limit, "offset": offset}
        if market:
            params["market"] = market
        if type_:
            params["type"] = type_
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self.get_json("/activity", params=params) or []

    def iter_activity(self, wallet: str, *, page_size: int = 500, **filters) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.get_activity(wallet, limit=page_size, offset=offset, **filters)
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return
            offset += len(batch)

    def get_positions(
        self,
        wallet: str,
        *,
        limit: int = 100,
        offset: int = 0,
        size_threshold: float | None = None,
    ) -> list[dict]:
        params: dict = {"user": wallet, "limit": limit, "offset": offset}
        if size_threshold is not None:
            params["sizeThreshold"] = size_threshold
        return self.get_json("/positions", params=params) or []

    def iter_positions(self, wallet: str, *, page_size: int = 500, **filters) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.get_positions(wallet, limit=page_size, offset=offset, **filters)
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return
            offset += len(batch)

    def get_trades(
        self,
        *,
        wallet: str | None = None,
        market: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        params: dict = {"limit": limit, "offset": offset}
        if wallet:
            params["user"] = wallet
        if market:
            params["market"] = market
        return self.get_json("/trades", params=params) or []

    def iter_trades(
        self,
        *,
        wallet: str | None = None,
        market: str | None = None,
        page_size: int = 500,
    ) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.get_trades(wallet=wallet, market=market, limit=page_size, offset=offset)
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return
            offset += len(batch)

    def get_value(self, wallet: str) -> float | None:
        """Current portfolio value in USDC, or None if not found."""
        rows = self.get_json("/value", params={"user": wallet}) or []
        if isinstance(rows, list) and rows:
            return float(rows[0].get("value", 0) or 0)
        return None

    # ---- market-scoped feeds ------------------------------------------------

    def get_holders(self, condition_id: str, *, limit: int = 100) -> list[dict]:
        """Top current holders of each outcome token for the given market.

        Returns a list shaped like:
            [{"token": "<id>", "holders": [{"proxyWallet": "0x...", "amount": 123.4, ...}, ...]}]
        """
        return self.get_json(
            "/holders",
            params={"market": condition_id, "limit": limit},
        ) or []

    def get_market_trades(self, condition_id: str, *, limit: int = 500, offset: int = 0) -> list[dict]:
        return self.get_trades(market=condition_id, limit=limit, offset=offset)
