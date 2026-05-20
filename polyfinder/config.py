"""Static configuration: endpoint URLs, rate limits, DB path.

No secrets here. Everything is overridable via environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Base URLs ---------------------------------------------------------------

GAMMA_API_URL = os.getenv("POLY_GAMMA_URL", "https://gamma-api.polymarket.com")
DATA_API_URL = os.getenv("POLY_DATA_API_URL", "https://data-api.polymarket.com")
CLOB_API_URL = os.getenv("POLY_CLOB_URL", "https://clob.polymarket.com")

# Goldsky public subgraph endpoints (one per concern).
# Source: github.com/Polymarket/polymarket-subgraph + community references.
SUBGRAPH_URLS = {
    "activity": os.getenv(
        "POLY_SUBGRAPH_ACTIVITY",
        "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/activity-polygon/0.0.4/gn",
    ),
    "pnl": os.getenv(
        "POLY_SUBGRAPH_PNL",
        "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/pnl-subgraph/0.0.14/gn",
    ),
    "orderbook": os.getenv(
        "POLY_SUBGRAPH_ORDERBOOK",
        "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.7/gn",
    ),
    "positions": os.getenv(
        "POLY_SUBGRAPH_POSITIONS",
        "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/positions-subgraph/0.0.7/gn",
    ),
}

# --- HTTP behavior -----------------------------------------------------------

HTTP_TIMEOUT_SEC = float(os.getenv("POLY_HTTP_TIMEOUT", "30"))
HTTP_MAX_RETRIES = int(os.getenv("POLY_HTTP_RETRIES", "4"))
HTTP_BACKOFF_BASE_SEC = float(os.getenv("POLY_HTTP_BACKOFF", "1.5"))
USER_AGENT = os.getenv("POLY_USER_AGENT", "polyfinder/0.1 (+local research tool)")

# Soft per-second rate cap for each client (seconds between requests).
RATE_LIMIT_DELAY_SEC = float(os.getenv("POLY_RATE_DELAY", "0.15"))

# --- Storage -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("POLYFINDER_DB", str(REPO_ROOT / "polyfinder.db")))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

EXPORT_DIR = Path(os.getenv("POLYFINDER_EXPORTS", str(REPO_ROOT / "exports")))


def ensure_dirs() -> None:
    """Make sure required directories exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
