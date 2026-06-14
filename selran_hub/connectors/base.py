"""
Base connector — interface that all connectors implement.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional


class BaseConnector(ABC):
    """Every data source connector must implement this interface."""

    def __init__(self, source: dict):
        self.source = source
        self.source_id = source["id"]
        self.name = source["name"]
        self.path = source.get("path")
        self.url = source.get("url")
        self.rules = source.get("rules", {})

    @abstractmethod
    def health_check(self) -> tuple[bool, Optional[str]]:
        """Return (ok, error_message). error_message is None if ok."""
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        """Return stats like table count, row count, size, etc."""
        ...

    @abstractmethod
    def list_tables(self) -> list[dict]:
        """Return list of tables / files with metadata."""
        ...

    @abstractmethod
    def preview(self, table_name: str, limit: int = 20) -> dict:
        """Return preview data: {columns, rows, total_rows}."""
        ...

    def get_type(self) -> str:
        return self.source.get("type", "unknown")
