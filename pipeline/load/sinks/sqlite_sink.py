"""
SQLite Sink — Writes processed data to SQLite database tables.

Stores market data, features, and pipeline metadata in relational format
for efficient querying and downstream consumption by the RL agent.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.config import SinkConfig
from pipeline.database.connection import DatabaseConnection
from pipeline.database.repository import MarketDataRepository, TickerRepository
from pipeline.events.bus import ObserverBus
from pipeline.load.sinks.base import AbstractSink, LoadResult

logger = logging.getLogger(__name__)


class SQLiteSink(AbstractSink):
    """Write processed data to SQLite database."""

    def __init__(
        self,
        config: SinkConfig,
        observer_bus: Optional[ObserverBus] = None,
        db_connection: Optional[DatabaseConnection] = None,
    ) -> None:
        super().__init__(config, observer_bus)
        self._db = db_connection
        self._own_connection = db_connection is None

    def _get_db(self) -> DatabaseConnection:
        if self._db is None:
            from pipeline.config import DatabaseConfig
            self._db = DatabaseConnection(
                DatabaseConfig(database_path=self.config.database_path)
            )
            self._db.connect()
            self._db.initialize_schema()
        return self._db

    def load(self, df: pd.DataFrame, partition_key: str) -> LoadResult:
        """Insert processed DataFrame rows into market_data table."""
        self._emit_event("LOAD_STARTED", {"sink_type": "sqlite", "partition_key": partition_key})

        db = self._get_db()
        ticker_repo = TickerRepository(db)
        market_repo = MarketDataRepository(db)

        # Ensure tickers exist
        if "Ticker" in df.columns:
            symbols = df["Ticker"].unique()
            for symbol in symbols:
                ticker_repo.get_by_symbol(symbol) or ticker_repo.insert(symbol.upper())

        # Build rows for bulk insert
        rows = []
        for _, row in df.iterrows():
            ticker_id = ticker_repo.get_by_symbol(
                str(row.get("Ticker", ""))
            ) or -1
            ts = str(row.name) if hasattr(row, "name") else str(row.get("timestamp", datetime.now(timezone.utc).isoformat()))

            # Handle DatetimeIndex
            if isinstance(row.name, pd.Timestamp):
                ts = row.name.isoformat()
            elif "Date" in df.columns:
                ts = str(row.get("Date", ts))

            rows.append((
                ticker_id,
                ts,
                str(row.get("timeframe", "1d")),
                float(row.get("Open", 0)),
                float(row.get("High", 0)),
                float(row.get("Low", 0)),
                float(row.get("Close", 0)),
                float(row.get("Volume", 0)),
                float(row.get("Adj Close", row.get("adjusted_close", 0))) if "Adj Close" in df.columns or "adjusted_close" in df.columns else None,
                str(row.get("data_source", "yahoo_finance")),
            ))

        market_repo.bulk_insert(rows)

        # Estimate bytes from database file size
        db_path = Path(self.config.database_path)
        bytes_written = db_path.stat().st_size if db_path.exists() else 0

        result = LoadResult(
            rows_written=len(df),
            bytes_written=bytes_written,
            partition_key=partition_key,
        )

        self._emit_event("LOAD_COMPLETED", {
            "sink_type": "sqlite",
            "rows_written": len(df),
            "bytes_written": bytes_written,
        })

        self.logger.info(
            "Wrote %d rows to SQLite (%s)", len(df), self.config.database_path
        )
        return result

    def close(self) -> None:
        """Close database connection if owned."""
        if self._db and self._own_connection:
            self._db.close()
