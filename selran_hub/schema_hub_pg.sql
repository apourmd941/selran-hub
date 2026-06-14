-- Hub — Postgres schema for the v3 own-store (Selran Launchpad)
--
-- Hub bridges user data sources (folder, duckdb, sqlite, api) to MCP clients.
-- The schema below is for hub's OWN state — the source REGISTRY + the dashboard's
-- client auth tokens. The bridged sources stay where they are:
--   - duckdb files: opened READ-ONLY by `connectors/duckdb_connector.py`
--   - sqlite files: opened by `connectors/sqlite_connector.py`
--   - folders + REST APIs: read by their respective connectors
--   - in-memory `duckdb.connect(":memory:")` in folder/api connectors stays
--     in-memory — it's transient query processing, never persistent.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS sources (
    -- Source UUID (preserved from the existing `sources.json` shape).
    id           TEXT PRIMARY KEY,
    -- The connector type — one of CONNECTOR_MAP keys in source_manager.py:
    --   "folder" | "duckdb" | "sqlite" | "api"
    type         TEXT NOT NULL,
    name         TEXT NOT NULL,
    -- Free-form per-connector config. SourceManager already serialises this as
    -- JSON in sources.json today, so JSONB is the cleanest one-to-one.
    config       JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    -- The full body of the source record (kept as a JSONB blob too, so adding
    -- per-connector fields doesn't require a schema migration; `config` is the
    -- "fast lookup" subset, this is the source of truth).
    body         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_type    ON sources(type);
CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);

-- Tiny key-value store for hub's other JSON-on-disk state. Today it holds the
-- single 'auth' row (replacing auth.json — `{"enabled": bool, "api_key": str}`).
-- A KV table is intentional: hub.config.py's auth-file structure could grow
-- (multi-client tokens, action scopes), and a JSONB value lets that evolve
-- without a schema change.
CREATE TABLE IF NOT EXISTS app_state (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
