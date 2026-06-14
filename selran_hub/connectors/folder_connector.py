"""
Folder connector — scans a directory for data files (CSV, Excel, JSON, Parquet).
Loads them into an in-memory DuckDB for querying.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import duckdb

from .base import BaseConnector

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".parquet", ".xlsx", ".xls"}


class FolderConnector(BaseConnector):

    def health_check(self) -> tuple[bool, Optional[str]]:
        if not self.path:
            return False, "No path configured"
        p = Path(self.path).expanduser()
        if not p.exists():
            return False, f"Path does not exist: {self.path}"
        if not p.is_dir():
            return False, f"Path is not a directory: {self.path}"
        return True, None

    def get_stats(self) -> dict:
        p = Path(self.path).expanduser()
        files = self._scan_files(p)
        total_size = sum(f.stat().st_size for f in files)
        return {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "file_types": list(set(f.suffix.lower() for f in files)),
        }

    def list_tables(self) -> list[dict]:
        p = Path(self.path).expanduser()
        files = self._scan_files(p)
        tables = []
        for f in sorted(files, key=lambda x: x.name):
            stat = f.stat()
            stem = f.stem.replace(" ", "_").replace("-", "_").lower()
            tables.append({
                "name": f.name,
                "table_name": stem,  # queryable name (used in SQL / preview / describe)
                "path": str(f),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "type": f.suffix.lower().lstrip("."),
                "modified": stat.st_mtime,
            })
        return tables

    def preview(self, table_name: str, limit: int = 20) -> dict:
        p = Path(self.path).expanduser()
        target = p / table_name
        if not target.exists():
            # Try case-insensitive match on full name, then on stem name
            for f in self._scan_files(p):
                stem = f.stem.replace(" ", "_").replace("-", "_").lower()
                if f.name.lower() == table_name.lower() or stem == table_name.lower():
                    target = f
                    break
            else:
                return {"error": f"File not found: {table_name}"}

        row_limit = min(limit, self.rules.get("row_limit", 1000))

        try:
            conn = duckdb.connect(":memory:")
            ext = target.suffix.lower()

            if ext in (".csv", ".tsv"):
                query = f"SELECT * FROM read_csv_auto('{target}') LIMIT {row_limit}"
            elif ext == ".json":
                query = f"SELECT * FROM read_json_auto('{target}') LIMIT {row_limit}"
            elif ext == ".jsonl":
                query = f"SELECT * FROM read_json_auto('{target}', format='newline_delimited') LIMIT {row_limit}"
            elif ext == ".parquet":
                query = f"SELECT * FROM read_parquet('{target}') LIMIT {row_limit}"
            elif ext in (".xlsx", ".xls"):
                conn.execute("INSTALL spatial; LOAD spatial;")
                query = f"SELECT * FROM st_read('{target}') LIMIT {row_limit}"
            else:
                return {"error": f"Unsupported file type: {ext}"}

            result = conn.execute(query)
            columns = [desc[0] for desc in result.description]
            rows = [list(row) for row in result.fetchall()]

            # Get total row count
            if ext in (".csv", ".tsv"):
                count_q = f"SELECT COUNT(*) FROM read_csv_auto('{target}')"
            elif ext == ".json":
                count_q = f"SELECT COUNT(*) FROM read_json_auto('{target}')"
            elif ext == ".parquet":
                count_q = f"SELECT COUNT(*) FROM read_parquet('{target}')"
            else:
                count_q = None

            total = None
            if count_q:
                try:
                    total = conn.execute(count_q).fetchone()[0]
                except Exception:
                    total = len(rows)

            conn.close()
            return {
                "columns": columns,
                "rows": _serialize_rows(rows),
                "total_rows": total or len(rows),
                "preview_rows": len(rows),
            }
        except Exception as e:
            return {"error": str(e)}

    def query(self, sql: str, limit: int = 1000) -> dict:
        """Execute SQL against folder files using DuckDB.

        Files are registered as tables by their stem name (filename without
        extension). E.g. 'patients.csv' becomes queryable as 'patients'.
        """
        BLOCKED = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}
        if self.rules.get("read_only", True):
            first_word = sql.strip().split()[0].upper() if sql.strip() else ""
            if first_word in BLOCKED:
                return {"error": f"Write operation blocked: {first_word}"}

        row_limit = min(limit, self.rules.get("row_limit", 1000))
        p = Path(self.path).expanduser()

        try:
            conn = duckdb.connect(":memory:")
            # Register every data file as a named view
            files = self._scan_files(p)
            registered = []
            seen_names: set[str] = set()
            # Sort files for consistent cross-platform ordering;
            # prefer tabular formats (.csv/.tsv/.parquet) over .json
            EXT_PRIORITY = {".csv": 0, ".tsv": 0, ".parquet": 1, ".xlsx": 2, ".xls": 2, ".json": 3, ".jsonl": 3}
            sorted_files = sorted(files, key=lambda f: (EXT_PRIORITY.get(f.suffix.lower(), 9), f.name.lower()))
            for f in sorted_files:
                name = f.stem.replace(" ", "_").replace("-", "_").lower()
                if name in seen_names:
                    # Use name_ext format for duplicates (e.g. test_data_json)
                    name = f"{name}_{f.suffix.lower().lstrip('.')}"
                seen_names.add(name)
                ext = f.suffix.lower()
                try:
                    if ext in (".csv", ".tsv"):
                        conn.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_csv_auto('{f}')")
                    elif ext == ".json":
                        conn.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_json_auto('{f}')")
                    elif ext == ".jsonl":
                        conn.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_json_auto('{f}', format='newline_delimited')")
                    elif ext == ".parquet":
                        conn.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_parquet('{f}')")
                    else:
                        continue
                    registered.append(name)
                except Exception:
                    continue  # skip files that can't be loaded

            result = conn.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = [list(row) for row in result.fetchmany(row_limit)]
            conn.close()
            return {
                "columns": columns,
                "rows": _serialize_rows(rows),
                "row_count": len(rows),
                "truncated": len(rows) >= row_limit,
                "available_tables": registered,
            }
        except Exception as e:
            return {"error": str(e)}

    def describe(self, table_name: str) -> dict:
        """Get descriptive statistics for a file."""
        p = Path(self.path).expanduser()
        target = None
        # Sort by extension priority so CSV/TSV win over JSON for same stem
        EXT_PRIORITY = {".csv": 0, ".tsv": 0, ".parquet": 1, ".xlsx": 2, ".xls": 2, ".json": 3, ".jsonl": 3}
        sorted_files = sorted(self._scan_files(p), key=lambda f: (EXT_PRIORITY.get(f.suffix.lower(), 9), f.name.lower()))
        for f in sorted_files:
            name = f.stem.replace(" ", "_").replace("-", "_").lower()
            if name == table_name.lower() or f.name.lower() == table_name.lower():
                target = f
                break
        if not target:
            return {"error": f"File not found: {table_name}"}

        try:
            conn = duckdb.connect(":memory:")
            ext = target.suffix.lower()
            if ext in (".csv", ".tsv"):
                read_fn = f"read_csv_auto('{target}')"
            elif ext == ".json":
                read_fn = f"read_json_auto('{target}')"
            elif ext == ".parquet":
                read_fn = f"read_parquet('{target}')"
            else:
                return {"error": f"Describe not supported for {ext}"}

            # Get numeric columns and compute stats
            cols_result = conn.execute(f"DESCRIBE SELECT * FROM {read_fn}").fetchall()
            columns_info = [{"name": r[0], "type": r[1]} for r in cols_result]

            total_rows = conn.execute(f"SELECT COUNT(*) FROM {read_fn}").fetchone()[0]

            # Summarize each column
            col_stats = []
            for col_info in columns_info:
                cname = col_info["name"]
                ctype = col_info["type"]
                try:
                    if "INT" in ctype.upper() or "FLOAT" in ctype.upper() or "DOUBLE" in ctype.upper() or "DECIMAL" in ctype.upper() or "NUMERIC" in ctype.upper():
                        s = conn.execute(f"""
                            SELECT
                                MIN("{cname}") as min_val,
                                MAX("{cname}") as max_val,
                                AVG("{cname}")::DOUBLE as mean_val,
                                STDDEV("{cname}")::DOUBLE as std_val,
                                COUNT("{cname}") as non_null,
                                COUNT(*) - COUNT("{cname}") as null_count
                            FROM {read_fn}
                        """).fetchone()
                        col_stats.append({
                            "column": cname, "type": ctype,
                            "min": s[0], "max": s[1], "mean": round(s[2], 4) if s[2] else None,
                            "std": round(s[3], 4) if s[3] else None,
                            "non_null": s[4], "null_count": s[5],
                        })
                    else:
                        s = conn.execute(f"""
                            SELECT
                                COUNT(DISTINCT "{cname}") as unique_count,
                                COUNT("{cname}") as non_null,
                                COUNT(*) - COUNT("{cname}") as null_count
                            FROM {read_fn}
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

    def _scan_files(self, root: Path) -> list[Path]:
        files = []
        try:
            for entry in root.rglob("*"):
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(entry)
        except PermissionError:
            pass
        return files


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
