"""Optional Postgres backend for the Hub's own store.

Hub's own state is just two JSON files today: `sources.json` (the configured-
source registry, owned by `SourceManager`) and `auth.json` (client-token
records, owned by `config.py`). This module mirrors that surface against a
managed Postgres database — when `HUB_DATABASE_URL` is set, `SourceManager`
and the auth helpers route through here; otherwise the legacy JSON-file path
is used (so developer/test runs stay unchanged — reversible).

**Bridged sources are NOT in scope** — the user data sources hub connects to
(`.duckdb` / `.sqlite` files, folders, REST APIs) live wherever the user
configured them; nothing here touches them.

psycopg is imported lazily so the JSON-file path doesn't need it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

SCHEMA_FILE = Path(__file__).parent / "schema_hub_pg.sql"


def backend_active() -> bool:
    """True iff `HUB_DATABASE_URL` is set (opt-in Postgres backend)."""
    return bool(os.environ.get("HUB_DATABASE_URL", "").strip())


def _dsn(url: str | None = None) -> str:
    dsn = (url or os.environ.get("HUB_DATABASE_URL", "")).strip()
    if not dsn:
        raise RuntimeError(
            "No Postgres DSN — set HUB_DATABASE_URL (the environment provides "
            "it via install.env=${managed_pg_url}) or pass url= explicitly."
        )
    return dsn


def _split_statements(sql: str) -> list[str]:
    """Strip `--` line comments, split on `;`. Good enough for our schema."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _connect(url: str | None = None):
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(_dsn(url), autocommit=True, row_factory=dict_row)


# ─── lifecycle ──────────────────────────────────────────────────────────


def pg_init_schema(url: str | None = None) -> None:
    """Apply `schema_hub_pg.sql` to the managed `hub` database. Idempotent."""
    statements = _split_statements(SCHEMA_FILE.read_text())
    with _connect(url) as cx:
        for stmt in statements:
            cx.execute(stmt)


# ─── source-registry surface (replaces sources.json) ───────────────────


def load_sources(url: str | None = None) -> list[dict]:
    """Every source row, in the same shape `SourceManager._load` produced from
    the JSON file (the `body` JSONB column is the source of truth)."""
    with _connect(url) as cx:
        rows = cx.execute(
            "SELECT body FROM sources ORDER BY created_at"
        ).fetchall()
        return [r["body"] for r in rows]


def save_sources(sources: Iterable[dict], url: str | None = None) -> None:
    """Replace the entire source set (mirroring `SourceManager._save`'s
    write-the-whole-list-to-disk semantics). Wrapped in a transaction so a
    crash mid-replace doesn't corrupt the registry."""
    sources = list(sources)
    import psycopg
    cx = psycopg.connect(_dsn(url), autocommit=False)
    try:
        cx.execute("DELETE FROM sources")
        for s in sources:
            sid = s.get("id")
            if not sid:
                continue
            cx.execute(
                "INSERT INTO sources (id, type, name, config, enabled, body) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb)",
                (
                    sid,
                    s.get("type", ""),
                    s.get("name", ""),
                    json.dumps(s.get("config", {})),
                    bool(s.get("enabled", True)),
                    json.dumps(s),
                ),
            )
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    finally:
        cx.close()


# ─── auth surface (replaces auth.json) ──────────────────────────────────
#
# auth.json today is a single record {"enabled": bool, "api_key": str}. The
# `app_state` KV table stores it under key='auth'; the JSONB value preserves
# the existing shape and lets it grow (future multi-client tokens, scopes)
# without a schema migration.


def load_auth(url: str | None = None) -> dict:
    """Read the auth record (`{"enabled": bool, "api_key": str}`). Returns {}
    if no row exists (the file-not-exists equivalent)."""
    with _connect(url) as cx:
        row = cx.execute(
            "SELECT value FROM app_state WHERE key = 'auth'"
        ).fetchone()
        return row["value"] if row else {}


def save_auth(data: dict, url: str | None = None) -> None:
    """Upsert the auth record. Matches the write-the-whole-file semantics of
    the existing `set_api_key` in `config.py`."""
    with _connect(url) as cx:
        cx.execute(
            "INSERT INTO app_state (key, value) VALUES ('auth', %s::jsonb) "
            "ON CONFLICT (key) DO UPDATE SET "
            "  value = EXCLUDED.value, updated_at = now()",
            (json.dumps(data or {}),),
        )
