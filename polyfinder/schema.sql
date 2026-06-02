-- Polyfinder SQLite schema.
-- All tables use INSERT ... ON CONFLICT DO UPDATE for idempotent re-ingest.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- users: one row per wallet (proxy address). Username is optional on Polymarket.
-- created_at_estimate is the best-effort proxy (min of first trade ts).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    wallet              TEXT PRIMARY KEY,
    username            TEXT,
    display_name        TEXT,
    bio                 TEXT,
    profile_image       TEXT,
    created_at_estimate INTEGER,   -- unix seconds
    first_trade_at      INTEGER,
    last_trade_at       INTEGER,
    n_trades            INTEGER DEFAULT 0,
    n_markets           INTEGER DEFAULT 0,
    realized_pnl        REAL DEFAULT 0,
    unrealized_pnl      REAL DEFAULT 0,
    volume_usdc         REAL DEFAULT 0,
    last_synced_at      INTEGER,
    raw_json            TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_created      ON users(created_at_estimate);
CREATE INDEX IF NOT EXISTS idx_users_last_trade   ON users(last_trade_at);
CREATE INDEX IF NOT EXISTS idx_users_pnl          ON users(realized_pnl);

-- ---------------------------------------------------------------------------
-- markets: one row per condition (resolution unit). slug is the human URL part.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS markets (
    condition_id        TEXT PRIMARY KEY,
    market_id           TEXT,
    slug                TEXT,
    question            TEXT,
    description         TEXT,
    category            TEXT,        -- single canonical category from Gamma
    event_slug          TEXT,
    outcome_count       INTEGER,
    outcomes_json       TEXT,        -- ["Yes","No"] etc
    token_ids_json      TEXT,        -- token id per outcome
    created_at          INTEGER,
    end_date            INTEGER,
    closed              INTEGER DEFAULT 0,   -- 0/1
    resolved            INTEGER DEFAULT 0,   -- 0/1
    resolved_outcome    TEXT,                -- e.g. "Yes" / "No" / "Drew" etc
    resolved_token_id   TEXT,
    resolution_source   TEXT,
    volume_usdc         REAL,
    liquidity_usdc      REAL,
    raw_json            TEXT,
    last_synced_at      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_markets_slug        ON markets(slug);
CREATE INDEX IF NOT EXISTS idx_markets_category    ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_resolved    ON markets(resolved, resolved_outcome);
CREATE INDEX IF NOT EXISTS idx_markets_end_date    ON markets(end_date);

-- ---------------------------------------------------------------------------
-- market_tags: many-to-many for the multi-tag case (e.g. Politics + Elections).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tags (
    condition_id        TEXT NOT NULL,
    tag                 TEXT NOT NULL,
    PRIMARY KEY (condition_id, tag),
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_market_tags_tag ON market_tags(tag);

-- ---------------------------------------------------------------------------
-- activities: every on-platform event for a wallet (trade/split/merge/redeem/reward).
-- id is the Polymarket activity id (string) or composite tx_hash:log_index fallback.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
    id              TEXT PRIMARY KEY,
    wallet          TEXT NOT NULL,
    type            TEXT NOT NULL,        -- trade|split|merge|redemption|reward|conversion
    side            TEXT,                 -- buy|sell (for trades)
    market_id       TEXT,
    condition_id    TEXT,
    outcome         TEXT,                 -- "Yes" / "No" / outcome label
    token_id        TEXT,
    size            REAL,                 -- shares
    price           REAL,                 -- 0..1
    size_usdc       REAL,                 -- size * price for trades
    ts              INTEGER NOT NULL,
    tx_hash         TEXT,
    raw_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_activities_wallet_ts   ON activities(wallet, ts);
CREATE INDEX IF NOT EXISTS idx_activities_condition   ON activities(condition_id);
CREATE INDEX IF NOT EXISTS idx_activities_type        ON activities(type);
CREATE INDEX IF NOT EXISTS idx_activities_ts          ON activities(ts);

-- ---------------------------------------------------------------------------
-- positions: current open positions per wallet x outcome token.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    wallet          TEXT NOT NULL,
    condition_id    TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    outcome         TEXT,
    size            REAL,                 -- shares held
    avg_price       REAL,                 -- weighted avg entry price
    current_price   REAL,
    current_value   REAL,
    realized_pnl    REAL,
    unrealized_pnl  REAL,
    last_synced_at  INTEGER,
    raw_json        TEXT,
    PRIMARY KEY (wallet, token_id)
);

CREATE INDEX IF NOT EXISTS idx_positions_wallet    ON positions(wallet);
CREATE INDEX IF NOT EXISTS idx_positions_condition ON positions(condition_id);

-- ---------------------------------------------------------------------------
-- wallet_features: derived per-wallet feature columns. Recomputed by features.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallet_features (
    wallet                      TEXT PRIMARY KEY,
    account_age_days            REAL,
    n_trades                    INTEGER,
    n_markets                   INTEGER,
    n_categories                INTEGER,
    realized_pnl                REAL,
    unrealized_pnl              REAL,
    total_volume_usdc           REAL,
    avg_trade_usdc              REAL,
    median_trade_usdc           REAL,
    win_rate_resolved           REAL,    -- wins / resolved bets
    n_resolved_bets             INTEGER,
    n_wins                      INTEGER,
    n_losses                    INTEGER,
    market_concentration_hhi    REAL,    -- Herfindahl over volume per market
    category_concentration_hhi  REAL,
    dominant_category           TEXT,
    inter_trade_seconds_p50     REAL,
    inter_trade_seconds_p95     REAL,
    inter_trade_seconds_cv      REAL,
    night_trade_ratio           REAL,    -- fraction of trades 00:00-06:00 UTC
    hours_active_count          INTEGER, -- distinct UTC hours seen
    round_stake_ratio           REAL,    -- fraction of trades on round USDC amounts
    redemption_count            INTEGER,
    split_count                 INTEGER,
    merge_count                 INTEGER,
    bot_score                   REAL,    -- 0..1 (also stored on user for filtering convenience)
    bot_reasons_json            TEXT,
    computed_at                 INTEGER
);

CREATE INDEX IF NOT EXISTS idx_wallet_features_bot ON wallet_features(bot_score);
CREATE INDEX IF NOT EXISTS idx_wallet_features_pnl ON wallet_features(realized_pnl);
CREATE INDEX IF NOT EXISTS idx_wallet_features_age ON wallet_features(account_age_days);

-- ---------------------------------------------------------------------------
-- per-(wallet, category) trade counts and PnL — supports category-scoped filters.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallet_category_stats (
    wallet          TEXT NOT NULL,
    category        TEXT NOT NULL,
    n_trades        INTEGER,
    volume_usdc     REAL,
    realized_pnl    REAL,
    n_wins          INTEGER,
    n_losses        INTEGER,
    PRIMARY KEY (wallet, category)
);

CREATE INDEX IF NOT EXISTS idx_wcs_category ON wallet_category_stats(category);

-- ---------------------------------------------------------------------------
-- discovery_runs: a log of every "find wallets" call so we can show provenance.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy        TEXT NOT NULL,   -- by_market | by_subgraph | by_holders | by_seed | expand
    params_json     TEXT,
    n_wallets       INTEGER,
    ran_at          INTEGER
);

CREATE TABLE IF NOT EXISTS discovery_wallets (
    run_id          INTEGER NOT NULL,
    wallet          TEXT NOT NULL,
    PRIMARY KEY (run_id, wallet),
    FOREIGN KEY (run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_disc_wallet ON discovery_wallets(wallet);
