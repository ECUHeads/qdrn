"""
SQLite Database Connection Manager.

Provides thread-safe connection handling with WAL mode, foreign key support,
and automatic schema initialization from schema.sql.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from pipeline.config import DatabaseConfig
from pipeline.errors import DatabaseError

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Manages SQLite connections with production-grade settings."""

    def __init__(self, config: DatabaseConfig | None = None):
        self._config = config or DatabaseConfig()
        self._connection: Optional[sqlite3.Connection] = None
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        db_path = Path(self._config.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """Establish or return existing database connection."""
        if self._connection is not None:
            try:
                self._connection.execute("SELECT 1")
                return self._connection
            except sqlite3.ProgrammingError:
                # Connection is closed, create new one
                self._connection = None

        try:
            self._connection = sqlite3.connect(
                self._config.database_path,
                timeout=self._config.timeout,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row

            # Enable WAL mode for concurrent reads
            if self._config.wal_mode:
                self._connection.execute("PRAGMA journal_mode = WAL")

            # Enable foreign key constraints
            if self._config.foreign_keys:
                self._connection.execute("PRAGMA foreign_keys = ON")

            # Set busy timeout
            self._connection.execute(
                f"PRAGMA busy_timeout = {self._config.busy_timeout}"
            )

            logger.info("Database connected: %s", self._config.database_path)
            return self._connection

        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to connect to database: {exc}") from exc

    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Database connection closed")
            except sqlite3.Error as exc:
                logger.error("Error closing database: %s", exc)
            finally:
                self._connection = None

    def initialize_schema(self, schema_path: str | Path = "schema.sql") -> None:
        """Execute schema.sql to create all tables, indexes, and views."""
        conn = self.connect()
        try:
            schema_text = Path(schema_path).read_text(encoding="utf-8")
            conn.executescript(schema_text)
            conn.commit()
            logger.info("Database schema initialized from %s", schema_path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Schema initialization failed: {exc}") from exc

    @property
    def connection(self) -> sqlite3.Connection:
        """Get active connection, creating one if necessary."""
        if not self._connection:
            return self.connect()
        return self._connection

    def __enter__(self) -> DatabaseConnection:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# Module-level singleton for convenience
_default_connection: Optional[DatabaseConnection] = None


def get_connection(config: DatabaseConfig | None = None) -> DatabaseConnection:
    """Get or create the default database connection singleton."""
    global _default_connection
    if _default_connection is None:
        _default_connection = DatabaseConnection(config)
    return _default_connection
