"""Goldsky GraphQL subgraph client.

Optional. Useful for historical scans (e.g. "all wallets that traded in [t0, t1]")
when the REST data-api isn't sufficient. Endpoints are configured in config.SUBGRAPH_URLS.

NOTE: Goldsky public subgraph URLs change occasionally. If a query 404s,
update the corresponding URL via the POLY_SUBGRAPH_* environment variables.
"""

from __future__ import annotations

from typing import Iterator

import httpx

from .. import config


class SubgraphClient:
    def __init__(self, kind: str = "pnl") -> None:
        if kind not in config.SUBGRAPH_URLS:
            raise ValueError(f"unknown subgraph kind: {kind}")
        self.url = config.SUBGRAPH_URLS[kind]
        self._client = httpx.Client(
            timeout=config.HTTP_TIMEOUT_SEC,
            headers={"User-Agent": config.USER_AGENT, "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SubgraphClient":
        return self

    def __exit__(self, *_a) -> None:
        self.close()

    def query(self, gql: str, variables: dict | None = None) -> dict:
        r = self._client.post(self.url, json={"query": gql, "variables": variables or {}})
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"subgraph errors: {data['errors']}")
        return data["data"]

    def paginate(
        self,
        gql_template: str,
        *,
        variables: dict | None = None,
        list_key: str,
        page_size: int = 1000,
    ) -> Iterator[dict]:
        """Cursor pagination by `id_gt` — convention for the-graph-style subgraphs.

        gql_template must accept `$first: Int`, `$idGt: String`, and any other variables.
        """
        last_id = ""
        while True:
            v = dict(variables or {})
            v.update({"first": page_size, "idGt": last_id})
            data = self.query(gql_template, v)
            batch = data.get(list_key) or []
            if not batch:
                return
            for item in batch:
                yield item
            if len(batch) < page_size:
                return
            last_id = batch[-1].get("id") or ""
            if not last_id:
                return
