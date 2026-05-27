"""
Repository Pattern — CRUD Operations for all database entities.

Each repository encapsulates data access logic for a specific entity,
providing type-safe methods with parameterized queries to prevent SQL injection.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from pipeline.config import DatabaseConfig
from pipeline.database.connection import DatabaseConnection
from pipeline.errors import DatabaseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ticker Repository
# ---------------------------------------------------------------------------

class TickerRepository:
    """CRUD operations for the tickers table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def insert(
        self,
        symbol: str,
        name: str = "",
        exchange: str = "",
        asset_class: str = "equity",
        currency: str = "USD",
    ) -> int:
        """Insert a new ticker. Returns the row id."""
        sql = """
            INSERT INTO tickers (symbol, name, exchange, asset_class, currency)
            VALUES (?, ?, ?, ?, ?)
        """
        try:
            cur = self._db.connection.execute(sql, (symbol, name, exchange, asset_class, currency))
            self._db.connection.commit()
            logger.info("Inserted ticker: %s", symbol)
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            logger.warning("Ticker already exists: %s", symbol)
            return self.get_by_symbol(symbol) or -1
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to insert ticker: {exc}", operation="insert") from exc

    def get_by_symbol(self, symbol: str) -> Optional[int]:
        """Get ticker id by symbol. Returns None if not found."""
        sql = "SELECT id FROM tickers WHERE symbol = ? COLLATE NOCASE"
        row = self._db.connection.execute(sql, (symbol.upper(),)).fetchone()
        return row["id"] if row else None

    def get_all_active(self) -> List[Dict[str, Any]]:
        """Return all active tickers."""
        sql = "SELECT * FROM v_active_tickers"
        rows = self._db.connection.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def update(
        self,
        ticker_id: int,
        *,
        name: Optional[str] = None,
        is_active: Optional[bool] = None,
        delisted_date: Optional[str] = None,
    ) -> None:
        """Update ticker fields."""
        fields: List[str] = []
        values: List[Any] = []

        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(1 if is_active else 0)
        if delisted_date is not None:
            fields.append("delisted_date = ?")
            values.append(delisted_date)

        if not fields:
            return

        fields.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(ticker_id)

        sql = f"UPDATE tickers SET {', '.join(fields)} WHERE id = ?"
        try:
            self._db.connection.execute(sql, values)
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to update ticker: {exc}", operation="update") from exc

    def bulk_insert(self, tickers: List[Dict[str, str]]) -> int:
        """Bulk insert multiple tickers. Returns count of inserted rows."""
        sql = """
            INSERT OR IGNORE INTO tickers (symbol, name, exchange, asset_class, currency)
            VALUES (?, ?, ?, ?, ?)
        """
        rows = [
            (t["symbol"], t.get("name", ""), t.get("exchange", ""), t.get("asset_class", "equity"), t.get("currency", "USD"))
            for t in tickers
        ]
        try:
            cur = self._db.connection.executemany(sql, rows)
            self._db.connection.commit()
            logger.info("Bulk inserted %d tickers", len(rows))
            return cur.rowcount
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to bulk insert tickers: {exc}", operation="bulk_insert") from exc


# ---------------------------------------------------------------------------
# Market Data Repository
# ---------------------------------------------------------------------------

class MarketDataRepository:
    """CRUD operations for the market_data table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def insert(
        self,
        ticker_id: int,
        timestamp: str,
        timeframe: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        adjusted_close: Optional[float] = None,
        data_source: str = "yahoo_finance",
    ) -> int:
        """Insert a single OHLCV record. Returns row id."""
        sql = """
            INSERT OR REPLACE INTO market_data
                (ticker_id, timestamp, timeframe, open, high, low, close, volume,
                 adjusted_close, data_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cur = self._db.connection.execute(
                sql,
                (ticker_id, timestamp, timeframe, open_, high, low, close, volume, adjusted_close, data_source),
            )
            self._db.connection.commit()
            return cur.lastrowid
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to insert market data: {exc}", operation="insert") from exc

    def bulk_insert(self, rows: List[tuple]) -> int:
        """Bulk insert OHLCV records. Each tuple: (ticker_id, ts, tf, o, h, l, c, v, adj, src)."""
        sql = """
            INSERT OR REPLACE INTO market_data
                (ticker_id, timestamp, timeframe, open, high, low, close, volume,
                 adjusted_close, data_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self._db.connection.executemany(sql, rows)
            self._db.connection.commit()
            logger.info("Bulk inserted %d market data rows", len(rows))
            return len(rows)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to bulk insert market data: {exc}", operation="bulk_insert") from exc

    def get_by_ticker(
        self,
        ticker_id: int,
        timeframe: str = "1d",
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Get market data for a ticker, ordered by timestamp DESC."""
        sql = """
            SELECT * FROM market_data
            WHERE ticker_id = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = self._db.connection.execute(sql, (ticker_id, timeframe, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_date_range(
        self,
        ticker_id: int,
        start: str,
        end: str,
        timeframe: str = "1d",
    ) -> List[Dict[str, Any]]:
        """Get market data within a date range."""
        sql = """
            SELECT * FROM market_data
            WHERE ticker_id = ? AND timeframe = ?
              AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        rows = self._db.connection.execute(
            sql, (ticker_id, timeframe, start, end)
        ).fetchall()
        return [dict(r) for r in rows]

    def latest(self, ticker_id: int, timeframe: str = "1d") -> Optional[Dict[str, Any]]:
        """Get the most recent market data point."""
        sql = """
            SELECT * FROM market_data
            WHERE ticker_id = ? AND timeframe = ?
            ORDER BY timestamp DESC LIMIT 1
        """
        row = self._db.connection.execute(sql, (ticker_id, timeframe)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Pipeline Run Repository
# ---------------------------------------------------------------------------

class PipelineRunRepository:
    """CRUD operations for the pipeline_runs table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def create(
        self,
        run_id: str,
        source_type: str,
        tickers: List[str],
        start_date: str,
        end_date: str,
        timeframe: str = "1d",
        config_json: Optional[str] = None,
    ) -> int:
        """Create a new pipeline run record."""
        sql = """
            INSERT INTO pipeline_runs
                (run_id, status, source_type, tickers_json, start_date, end_date,
                 timeframe, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cur = self._db.connection.execute(
                sql,
                (run_id, "running", source_type, json.dumps(tickers), start_date, end_date, timeframe, config_json),
            )
            self._db.connection.commit()
            return cur.lastrowid
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to create pipeline run: {exc}", operation="create") from exc

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        rows_extracted: int = 0,
        rows_transformed: int = 0,
        rows_loaded: int = 0,
        bytes_written: int = 0,
        duration_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update pipeline run status and metrics."""
        fields = ["status = ?"]
        values: List[Any] = [status]

        if rows_extracted:
            fields.append("rows_extracted = ?")
            values.append(rows_extracted)
        if rows_transformed:
            fields.append("rows_transformed = ?")
            values.append(rows_transformed)
        if rows_loaded:
            fields.append("rows_loaded = ?")
            values.append(rows_loaded)
        if bytes_written:
            fields.append("bytes_written = ?")
            values.append(bytes_written)
        if duration_ms is not None:
            fields.append("duration_ms = ?")
            values.append(duration_ms)
        if error_message:
            fields.append("error_message = ?")
            values.append(error_message)
        if status in ("completed", "failed"):
            fields.append("completed_at = ?")
            values.append(datetime.now(timezone.utc).isoformat())

        values.append(run_id)
        sql = f"UPDATE pipeline_runs SET {', '.join(fields)} WHERE run_id = ?"
        try:
            self._db.connection.execute(sql, values)
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to update pipeline run: {exc}", operation="update_status") from exc

    def get_by_run_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get pipeline run by run_id."""
        row = self._db.connection.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent pipeline runs."""
        rows = self._db.connection.execute(
            "SELECT * FROM v_pipeline_summary LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Trading Signal Repository
# ---------------------------------------------------------------------------

class TradingSignalRepository:
    """CRUD operations for the trading_signals table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def insert(
        self,
        ticker_id: int,
        timestamp: str,
        signal_type: str,
        confidence: float,
        position_size: Optional[float] = None,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        features_json: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> int:
        """Insert a new trading signal."""
        sql = """
            INSERT INTO trading_signals
                (ticker_id, timestamp, signal_type, confidence, position_size,
                 entry_price, stop_loss, take_profit, features_json, model_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cur = self._db.connection.execute(
                sql,
                (ticker_id, timestamp, signal_type, confidence, position_size,
                 entry_price, stop_loss, take_profit, features_json, model_version),
            )
            self._db.connection.commit()
            return cur.lastrowid
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to insert trading signal: {exc}", operation="insert") from exc

    def get_pending(self, ticker_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all pending signals, optionally filtered by ticker."""
        if ticker_id:
            rows = self._db.connection.execute(
                "SELECT * FROM trading_signals WHERE status = 'pending' AND ticker_id = ?",
                (ticker_id,),
            ).fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT * FROM trading_signals WHERE status = 'pending'"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_status(self, signal_id: int, status: str) -> None:
        """Update signal execution status."""
        sql = """
            UPDATE trading_signals
            SET status = ?, executed_at = ?
            WHERE id = ?
        """
        self._db.connection.execute(
            sql, (status, datetime.now(timezone.utc).isoformat() if status == "executed" else None, signal_id)
        )
        self._db.connection.commit()


# ---------------------------------------------------------------------------
# Position Repository
# ---------------------------------------------------------------------------

class PositionRepository:
    """CRUD operations for the positions table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def open_position(
        self,
        ticker_id: int,
        side: str,
        quantity: float,
        entry_price: float,
        signal_id: Optional[int] = None,
    ) -> int:
        """Open a new position."""
        sql = """
            INSERT INTO positions (ticker_id, signal_id, side, quantity, entry_price)
            VALUES (?, ?, ?, ?, ?)
        """
        cur = self._db.connection.execute(sql, (ticker_id, signal_id, side, quantity, entry_price))
        self._db.connection.commit()
        return cur.lastrowid

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> None:
        """Close an existing position."""
        sql = """
            UPDATE positions
            SET status = 'closed', closed_at = ?, exit_price = ?,
                commission = ?, slippage = ?
            WHERE id = ?
        """
        self._db.connection.execute(
            sql, (datetime.now(timezone.utc).isoformat(), exit_price, commission, slippage, position_id)
        )
        self._db.connection.commit()

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions with ticker info."""
        rows = self._db.connection.execute("SELECT * FROM v_open_positions").fetchall()
        return [dict(r) for r in rows]

    def update_current_price(self, position_id: int, current_price: float) -> None:
        """Update the current market price for an open position."""
        self._db.connection.execute(
            "UPDATE positions SET current_price = ? WHERE id = ?",
            (current_price, position_id),
        )
        self._db.connection.commit()


# ---------------------------------------------------------------------------
# Risk Metric Repository
# ---------------------------------------------------------------------------

class RiskMetricRepository:
    """CRUD operations for the risk_metrics table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def upsert(
        self,
        date: str,
        total_equity: float,
        daily_return: float = 0.0,
        sharpe_ratio: Optional[float] = None,
        max_drawdown: float = 0.0,
        current_drawdown: float = 0.0,
        win_rate: float = 0.0,
        total_trades: int = 0,
        winning_trades: int = 0,
        losing_trades: int = 0,
    ) -> None:
        """Insert or update daily risk metrics."""
        sql = """
            INSERT INTO risk_metrics
                (date, total_equity, daily_return, sharpe_ratio, max_drawdown,
                 current_drawdown, win_rate, total_trades, winning_trades, losing_trades)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_equity = excluded.total_equity,
                daily_return = excluded.daily_return,
                sharpe_ratio = excluded.sharpe_ratio,
                max_drawdown = excluded.max_drawdown,
                current_drawdown = excluded.current_drawdown,
                win_rate = excluded.win_rate,
                total_trades = excluded.total_trades,
                winning_trades = excluded.winning_trades,
                losing_trades = excluded.losing_trades,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """
        self._db.connection.execute(
            sql,
            (date, total_equity, daily_return, sharpe_ratio, max_drawdown,
             current_drawdown, win_rate, total_trades, winning_trades, losing_trades),
        )
        self._db.connection.commit()

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Get the most recent risk metrics record."""
        row = self._db.connection.execute(
            "SELECT * FROM risk_metrics ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_by_date(self, date: str) -> Optional[Dict[str, Any]]:
        """Get risk metrics for a specific date."""
        row = self._db.connection.execute(
            "SELECT * FROM risk_metrics WHERE date = ?", (date,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Audit Log Repository
# ---------------------------------------------------------------------------

class AuditLogRepository:
    """CRUD operations for the audit_log table."""

    def __init__(self, db: DatabaseConnection):
        self._db = db

    def log(
        self,
        action: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        user: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record an audit log entry."""
        sql = """
            INSERT INTO audit_log (action, entity_type, entity_id, user, details_json)
            VALUES (?, ?, ?, ?, ?)
        """
        cur = self._db.connection.execute(
            sql,
            (action, entity_type, entity_id, user, json.dumps(details) if details else None),
        )
        self._db.connection.commit()
        return cur.lastrowid

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent audit log entries."""
        rows = self._db.connection.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
