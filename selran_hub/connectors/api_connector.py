"""
API connector — connects to REST APIs.
Treats each endpoint as a "table". Supports query-like filtering
and descriptive statistics on API response data.
"""

from __future__ import annotations

import json
from typing import Optional

import httpx

from .base import BaseConnector


class APIConnector(BaseConnector):

    def _get_endpoints(self) -> list[dict]:
        return self.source.get("rules", {}).get("endpoints", [])

    def health_check(self) -> tuple[bool, Optional[str]]:
        if not self.url:
            return False, "No URL configured"
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(self.url)
                if resp.status_code < 400:
                    return True, None
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def get_stats(self) -> dict:
        endpoints = self._get_endpoints()
        return {
            "base_url": self.url,
            "endpoint_count": len(endpoints) if endpoints else 0,
        }

    def list_tables(self) -> list[dict]:
        """Each configured endpoint is treated as a 'table'."""
        endpoints = self._get_endpoints()
        if not endpoints:
            return [{
                "name": "root",
                "path": "/",
                "method": "GET",
                "description": "Base URL — configure endpoints in rules to see more",
            }]
        return [
            {
                "name": ep.get("name", ep.get("path", "unknown")),
                "path": ep.get("path", "/"),
                "method": ep.get("method", "GET"),
                "description": ep.get("description", ""),
            }
            for ep in endpoints
        ]

    def _fetch_endpoint(self, endpoint: dict, limit: int = 1000) -> tuple[list[str], list[list], Optional[str]]:
        """Fetch data from an endpoint. Returns (columns, rows, error)."""
        try:
            url = self.url.rstrip("/") + endpoint.get("path", "/")
            method = endpoint.get("method", "GET").upper()
            headers = endpoint.get("headers", {})
            params = endpoint.get("params", {})

            with httpx.Client(timeout=30) as client:
                if method == "GET":
                    params["limit"] = limit
                    resp = client.get(url, params=params, headers=headers)
                elif method == "POST":
                    resp = client.post(url, json=endpoint.get("body", {}), headers=headers)
                else:
                    resp = client.request(method, url, headers=headers)

                if resp.status_code >= 400:
                    return [], [], f"HTTP {resp.status_code}: {resp.text[:500]}"

                data = resp.json()

                # Handle different response shapes
                if isinstance(data, list):
                    rows_data = data[:limit]
                elif isinstance(data, dict):
                    for key in ("data", "results", "items", "records", "rows", "entries"):
                        if key in data and isinstance(data[key], list):
                            rows_data = data[key][:limit]
                            break
                    else:
                        rows_data = [data]
                else:
                    return [], [], "Unexpected response format"

                if rows_data and isinstance(rows_data[0], dict):
                    columns = list(rows_data[0].keys())
                    rows = [[row.get(c) for c in columns] for row in rows_data]
                else:
                    columns = ["value"]
                    rows = [[r] for r in rows_data]

                return columns, rows, None
        except Exception as e:
            return [], [], str(e)

    def _resolve_endpoint(self, table_name: str) -> Optional[dict]:
        """Find an endpoint by name or path."""
        endpoints = self._get_endpoints()
        for ep in endpoints:
            if ep.get("name") == table_name or ep.get("path") == table_name:
                return ep
        if table_name in ("root", "/"):
            return {"path": "/", "method": "GET"}
        return None

    def preview(self, table_name: str, limit: int = 20) -> dict:
        """Fetch data from an endpoint."""
        endpoint = self._resolve_endpoint(table_name)
        if not endpoint:
            return {"error": f"Endpoint not found: {table_name}"}

        row_limit = min(limit, self.rules.get("row_limit", 1000))
        columns, rows, error = self._fetch_endpoint(endpoint, row_limit)
        if error:
            return {"error": error}

        return {
            "columns": columns,
            "rows": _serialize_rows(rows),
            "total_rows": len(rows),
            "preview_rows": len(rows),
        }

    def query(self, sql: str, limit: int = 1000) -> dict:
        """Execute a SQL-like query against API data using DuckDB.

        Fetches all configured endpoints, loads them as named tables in
        an in-memory DuckDB, then runs the SQL query against them.
        """
        try:
            import duckdb
        except ImportError:
            return {"error": "DuckDB required for API queries. Run: pip install duckdb"}

        row_limit = min(limit, self.rules.get("row_limit", 1000))

        # Block write operations
        BLOCKED = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}
        if self.rules.get("read_only", True):
            first_word = sql.strip().split()[0].upper() if sql.strip() else ""
            if first_word in BLOCKED:
                return {"error": f"Write operation blocked: {first_word}"}

        try:
            conn = duckdb.connect(":memory:")
            registered = []
            endpoints = self._get_endpoints()
            if not endpoints:
                endpoints = [{"name": "root", "path": "/", "method": "GET"}]

            for ep in endpoints:
                name = ep.get("name", ep.get("path", "unknown"))
                name = name.strip("/").replace("/", "_").replace("-", "_").replace(" ", "_").lower()
                if not name:
                    name = "root"

                columns, rows, error = self._fetch_endpoint(ep)
                if error or not columns:
                    continue

                # Create DuckDB table from fetched data
                col_defs = ", ".join(f'"{c}" VARCHAR' for c in columns)
                conn.execute(f'CREATE TABLE "{name}" ({col_defs})')
                if rows:
                    placeholders = ", ".join(["?"] * len(columns))
                    for row in rows:
                        safe_row = [str(v) if v is not None else None for v in row]
                        conn.execute(f'INSERT INTO "{name}" VALUES ({placeholders})', safe_row)
                registered.append(name)

            if not registered:
                conn.close()
                return {"error": "No endpoint data could be loaded"}

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
        """Get descriptive statistics for an API endpoint's response data."""
        endpoint = self._resolve_endpoint(table_name)
        if not endpoint:
            return {"error": f"Endpoint not found: {table_name}"}

        columns, rows, error = self._fetch_endpoint(endpoint)
        if error:
            return {"error": error}
        if not columns or not rows:
            return {"error": "No data returned from endpoint"}

        total_rows = len(rows)
        col_stats = []

        for col_idx, col_name in enumerate(columns):
            values = [row[col_idx] for row in rows]
            non_null = [v for v in values if v is not None]
            null_count = total_rows - len(non_null)

            # Try to detect numeric column
            numeric_vals = []
            for v in non_null:
                try:
                    numeric_vals.append(float(v))
                except (ValueError, TypeError):
                    break  # Not all values are numeric — treat as text

            if len(numeric_vals) == len(non_null) and numeric_vals:
                mean = sum(numeric_vals) / len(numeric_vals)
                variance = sum((x - mean) ** 2 for x in numeric_vals) / max(len(numeric_vals) - 1, 1)
                std = variance ** 0.5
                col_stats.append({
                    "column": col_name, "type": "numeric",
                    "min": min(numeric_vals),
                    "max": max(numeric_vals),
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                    "non_null": len(non_null),
                    "null_count": null_count,
                })
            else:
                unique_count = len(set(str(v) for v in non_null))
                col_stats.append({
                    "column": col_name, "type": "text",
                    "unique_values": unique_count,
                    "non_null": len(non_null),
                    "null_count": null_count,
                })

        return {
            "table": table_name,
            "total_rows": total_rows,
            "columns": col_stats,
        }


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
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return str(v)

    return [[_convert(cell) for cell in row] for row in rows]
