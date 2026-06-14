"""
SQLite connector — connects to .sqlite / .db database files.
Read-only access with SQL safety enforcement.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .base import BaseConnector

BLOCKED_SQL = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"}


class SQLiteConnector(BaseConnector):

    def _connect(self) -> sqlite3.Connection:
        p = Path(self.path).expanduser()
        uri = f"file:{p}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def health_check(self) -> tuple[bool, Optional[str]]:
        if not self.path:
            return False, "No path configured"
        p = Path(self.path).expanduser()
        if not p.exists():
            return False, f"Database not found: {self.path}"
        try:
            conn = self._connect()
            conn.execute("SELECT 1")
            conn.close()
            return True, None
        except Exception as e:
            return False, str(e)

    def get_stats(self) -> dict:
        p = Path(self.path).expanduser()
        try:
            conn = self._connect()
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            total_rows = 0
            for (tbl,) in tables:
                try:
                    cnt = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    total_rows += cnt
                except Exception:
                    pass
            conn.close()
            return {
                "table_count": len(tables),
                "total_rows": total_rows,
                "size_bytes": p.stat().st_size,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            }
        except Exception as e:
            return {"error": str(e)}

    def list_tables(self) -> list[dict]:
        try:
            conn = self._connect()
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            result = []
            for (tbl,) in tables:
                try:
                    cnt = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    cols = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                    result.append({
                        "name": tbl,
                        "row_count": cnt,
                        "column_count": len(cols),
                        "columns": [{"name": c[1], "type": c[2] or "TEXT"} for c in cols],
                    })
                except Exception:
                    result.append({"name": tbl, "row_count": None, "column_count": None})
            conn.close()
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def preview(self, table_name: str, limit: int = 20) -> dict:
        row_limit = min(limit, self.rules.get("row_limit", 1000))
        try:
            conn = self._connect()
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            if table_name not in tables:
                conn.close()
                return {"error": f"Table not found: {table_name}"}

            cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT {row_limit}')
            columns = [desc[0] for desc in cursor.description]
            rows = [list(row) for row in cursor.fetchall()]
            total = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            conn.close()

            return {
                "columns": columns,
                "rows": _serialize_rows(rows),
                "total_rows": total,
                "preview_rows": len(rows),
            }
        except Exception as e:
            return {"error": str(e)}

    def query(self, sql: str, limit: int = 1000) -> dict:
        """Execute a read-only SQL query."""
        if self.rules.get("read_only", True):
            first_word = sql.strip().split()[0].upper() if sql.strip() else ""
            if first_word in BLOCKED_SQL:
                return {"error": f"Write operation blocked: {first_word}"}

        row_limit = min(limit, self.rules.get("row_limit", 1000))
        try:
            conn = self._connect()
            cursor = conn.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            rows = [list(row) for row in cursor.fetchmany(row_limit)]
            conn.close()
            return {
                "columns": columns,
                "rows": _serialize_rows(rows),
                "row_count": len(rows),
                "truncated": len(rows) >= row_limit,
            }
        except Exception as e:
            return {"error": str(e)}

    def describe(self, table_name: str) -> dict:
        """Get descriptive statistics for a table."""
        try:
            conn = self._connect()
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            if table_name not in tables:
                conn.close()
                return {"error": f"Table not found: {table_name}"}

            total_rows = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]

            # Get column info via PRAGMA
            cols = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()

            col_stats = []
            for col_info in cols:
                cname = col_info[1]
                ctype = (col_info[2] or "TEXT").upper()
                try:
                    if any(t in ctype for t in ("INT", "REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")):
                        s = conn.execute(f"""
                            SELECT
                                MIN("{cname}"), MAX("{cname}"),
                                AVG(CAST("{cname}" AS REAL)),
                                COUNT("{cname}"),
                                COUNT(*) - COUNT("{cname}")
                            FROM "{table_name}"
                        """).fetchone()
                        # SQLite doesn't have STDDEV, compute manually
                        mean = s[2]
                        std = None
                        if mean is not None and total_rows > 1:
                            try:
                                var_row = conn.execute(f"""
                                    SELECT AVG(("{cname}" - {mean}) * ("{cname}" - {mean}))
                                    FROM "{table_name}" WHERE "{cname}" IS NOT NULL
                                """).fetchone()
                                if var_row[0] is not None:
                                    std = round(var_row[0] ** 0.5, 4)
                            except Exception:
                                pass
                        col_stats.append({
                            "column": cname, "type": ctype,
                            "min": s[0], "max": s[1],
                            "mean": round(mean, 4) if mean is not None else None,
                            "std": std,
                            "non_null": s[3], "null_count": s[4],
                        })
                    else:
                        s = conn.execute(f"""
                            SELECT
                                COUNT(DISTINCT "{cname}"),
                                COUNT("{cname}"),
                                COUNT(*) - COUNT("{cname}")
                            FROM "{table_name}"
                        """).fetchone()
                        col_stats.append({
                            "column": cname, "type": ctype,
                            "unique_values": s[0], "non_null": s[1], "null_count": s[2],
                        })
                except Exception:
                    col_stats.append({"column": cname, "type": ctype, "error": "could not compute stats"})

            conn.close()
            return {
                "table": table_name,
                "total_rows": total_rows,
                "columns": col_stats,
            }
        except Exception as e:
            return {"error": str(e)}


def _serialize_rows(rows: list) -> list:
    """Convert rows to JSON-safe values."""
    import decimal
    from datetime import date, datetime

    def _convert(v):
        if v is None:
            return None
        if isinstance(v, (int, float, str, bool)):
            return v
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, bytes):
            return v.hex()
        return str(v)

    return [[_convert(cell) for cell in row] for row in rows]
