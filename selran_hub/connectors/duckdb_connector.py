"""
DuckDB connector — connects to .duckdb database files.
Read-only access with SQL safety enforcement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from .base import BaseConnector

BLOCKED_SQL = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"}


class DuckDBConnector(BaseConnector):

    def _connect(self) -> duckdb.DuckDBPyConnection:
        p = Path(self.path).expanduser()
        return duckdb.connect(str(p), read_only=True)

    def health_check(self) -> tuple[bool, Optional[str]]:
        if not self.path:
            return False, "No path configured"
        p = Path(self.path).expanduser()
        if not p.exists():
            return False, f"Database not found: {self.path}"
        if not p.suffix == ".duckdb":
            return False, f"Not a DuckDB file: {self.path}"
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
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
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
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
            result = []
            for (tbl,) in tables:
                try:
                    cnt = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    cols = conn.execute(
                        f"SELECT column_name, data_type FROM information_schema.columns "
                        f"WHERE table_name = '{tbl}' AND table_schema = 'main'"
                    ).fetchall()
                    result.append({
                        "name": tbl,
                        "row_count": cnt,
                        "column_count": len(cols),
                        "columns": [{"name": c[0], "type": c[1]} for c in cols],
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
            # Verify table exists
            tables = [
                r[0] for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            ]
            if table_name not in tables:
                conn.close()
                return {"error": f"Table not found: {table_name}"}

            result = conn.execute(f'SELECT * FROM "{table_name}" LIMIT {row_limit}')
            columns = [desc[0] for desc in result.description]
            rows = [list(row) for row in result.fetchall()]
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
            result = conn.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = [list(row) for row in result.fetchmany(row_limit)]
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
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            ]
            if table_name not in tables:
                conn.close()
                return {"error": f"Table not found: {table_name}"}

            total_rows = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]

            # Get column info
            cols = conn.execute(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{table_name}' AND table_schema = 'main'"
            ).fetchall()

            col_stats = []
            for cname, ctype in cols:
                try:
                    if any(t in ctype.upper() for t in ("INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "BIGINT", "SMALLINT")):
                        s = conn.execute(f"""
                            SELECT
                                MIN("{cname}"), MAX("{cname}"),
                                AVG("{cname}")::DOUBLE, STDDEV("{cname}")::DOUBLE,
                                COUNT("{cname}"), COUNT(*) - COUNT("{cname}")
                            FROM "{table_name}"
                        """).fetchone()
                        col_stats.append({
                            "column": cname, "type": ctype,
                            "min": s[0], "max": s[1],
                            "mean": round(s[2], 4) if s[2] else None,
                            "std": round(s[3], 4) if s[3] else None,
                            "non_null": s[4], "null_count": s[5],
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
