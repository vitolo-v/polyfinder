"""Gamma API: markets, events, slugs, tags, resolution metadata.

Base: https://gamma-api.polymarket.com
"""

from __future__ import annotations

from typing import Iterator

from .. import config
from ._http import PolyClient


class GammaClient(PolyClient):
    def __init__(self) -> None:
        super().__init__(config.GAMMA_API_URL)

    # -- markets --------------------------------------------------------------

    def get_market(self, market_id: str) -> dict:
        """Look up a single market by Gamma numeric id."""
        return self.get_json(f"/markets/{market_id}")

    def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        closed: bool | None = None,
        active: bool | None = None,
        archived: bool | None = None,
        slug: str | None = None,
        condition_ids: list[str] | None = None,
        order: str | None = None,
        ascending: bool | None = None,
    ) -> list[dict]:
        params: dict = {"limit": limit, "offset": offset}
        if closed is not None:
            params["closed"] = "true" if closed else "false"
        if active is not None:
            params["active"] = "true" if active else "false"
        if archived is not None:
            params["archived"] = "true" if archived else "false"
        if slug:
            params["slug"] = slug
        if condition_ids:
            # Gamma accepts repeated query param style
            params["condition_ids"] = condition_ids
        if order:
            params["order"] = order
            if ascending is not None:
                params["ascending"] = "true" if ascending else "false"
        return self.get_json("/markets", params=params) or []

    def iter_markets(self, *, page_size: int = 200, **filters) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.list_markets(limit=page_size, offset=offset, **filters)
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return
            offset += len(batch)

    def market_by_slug(self, slug: str) -> dict | None:
        rows = self.list_markets(slug=slug, limit=1)
        return rows[0] if rows else None

    # -- events ---------------------------------------------------------------

    def list_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        closed: bool | None = None,
        active: bool | None = None,
        archived: bool | None = None,
        tag: str | None = None,
        order: str | None = None,
        ascending: bool | None = None,
    ) -> list[dict]:
        params: dict = {"limit": limit, "offset": offset}
        if closed is not None:
            params["closed"] = "true" if closed else "false"
        if active is not None:
            params["active"] = "true" if active else "false"
        if archived is not None:
            params["archived"] = "true" if archived else "false"
        if tag:
            params["tag"] = tag
        if order:
            params["order"] = order
            if ascending is not None:
                params["ascending"] = "true" if ascending else "false"
        return self.get_json("/events", params=params) or []

    def iter_events(self, *, page_size: int = 100, **filters) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.list_events(limit=page_size, offset=offset, **filters)
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return
            offset += len(batch)

    def event_by_slug(self, slug: str) -> dict | None:
        # Gamma /events supports the `slug` filter too.
        rows = self.get_json("/events", params={"slug": slug, "limit": 1}) or []
        return rows[0] if rows else None
