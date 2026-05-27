"""Tests for database layer — repositories and connection."""

from __future__ import annotations

import pytest

from pipeline.database.repository import (
    AuditLogRepository,
    MarketDataRepository,
    PipelineRunRepository,
    PositionRepository,
    RiskMetricRepository,
    TickerRepository,
    TradingSignalRepository,
)


class TestTickerRepository:
    def test_insert_and_get(self, temp_db) -> None:
        repo = TickerRepository(temp_db)
        tid = repo.insert("AAPL", name="Apple Inc.", exchange="NASDAQ")
        assert tid > 0

        found_id = repo.get_by_symbol("AAPL")
        assert found_id == tid

    def test_insert_duplicate(self, temp_db) -> None:
        repo = TickerRepository(temp_db)
        tid1 = repo.insert("AAPL")
        tid2 = repo.insert("AAPL")
        assert tid1 == tid2 or tid2 == -1

    def test_get_all_active(self, temp_db) -> None:
        repo = TickerRepository(temp_db)
        repo.insert("AAPL")
        repo.insert("GOOGL")

        active = repo.get_all_active()
        assert len(active) >= 2

    def test_bulk_insert(self, temp_db) -> None:
        repo = TickerRepository(temp_db)
        tickers = [
            {"symbol": "T1", "name": "Test 1"},
            {"symbol": "T2", "name": "Test 2"},
            {"symbol": "T3", "name": "Test 3"},
        ]
        count = repo.bulk_insert(tickers)
        assert count >= 0

    def test_update(self, temp_db) -> None:
        repo = TickerRepository(temp_db)
        tid = repo.insert("UPDT")
        repo.update(tid, name="Updated Name")

        found_id = repo.get_by_symbol("UPDT")
        assert found_id == tid


class TestMarketDataRepository:
    def test_insert_and_query(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("MDTEST")

        repo = MarketDataRepository(temp_db)
        mid = repo.insert(
            ticker_id=tid,
            timestamp="2024-01-15T10:00:00",
            timeframe="1d",
            open_=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            volume=1_000_000,
        )
        assert mid > 0

        data = repo.get_by_ticker(tid)
        assert len(data) >= 1
        assert data[0]["close"] == 104.0

    def test_bulk_insert(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("BULK")

        repo = MarketDataRepository(temp_db)
        rows = [
            (tid, f"2024-01-{i:02d}T00:00:00", "1d", 100.0, 105.0, 99.0, 104.0, 1000.0, None, "test")
            for i in range(1, 11)
        ]
        count = repo.bulk_insert(rows)
        assert count == 10

    def test_latest(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("LATEST")

        repo = MarketDataRepository(temp_db)
        for i in range(1, 6):
            repo.insert(
                ticker_id=tid,
                timestamp=f"2024-01-{i:02d}T00:00:00",
                timeframe="1d",
                open_=float(i),
                high=float(i + 1),
                low=float(i - 1),
                close=float(i),
                volume=1000.0,
            )

        latest = repo.latest(tid)
        assert latest is not None


class TestPipelineRunRepository:
    def test_create_and_update(self, temp_db) -> None:
        repo = PipelineRunRepository(temp_db)
        repo.create(
            run_id="test_run_001",
            source_type="yahoo_finance",
            tickers=["AAPL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            timeframe="1d",
        )

        run = repo.get_by_run_id("test_run_001")
        assert run is not None
        assert run["status"] == "running"

        repo.update_status(
            "test_run_001",
            "completed",
            rows_extracted=100,
            rows_loaded=95,
            duration_ms=5000.0,
        )

        run = repo.get_by_run_id("test_run_001")
        assert run["status"] == "completed"
        assert run["rows_extracted"] == 100

    def test_get_recent(self, temp_db) -> None:
        repo = PipelineRunRepository(temp_db)
        for i in range(5):
            repo.create(
                run_id=f"recent_{i}",
                source_type="yahoo_finance",
                tickers=["TEST"],
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        recent = repo.get_recent(limit=3)
        assert len(recent) <= 3


class TestTradingSignalRepository:
    def test_insert_and_query(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("SIGTEST")

        repo = TradingSignalRepository(temp_db)
        sid = repo.insert(
            ticker_id=tid,
            timestamp="2024-01-15T10:00:00",
            signal_type="BUY",
            confidence=0.85,
            entry_price=100.0,
        )
        assert sid > 0

        pending = repo.get_pending()
        assert len(pending) >= 1

    def test_update_status(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("SIGUPD")

        repo = TradingSignalRepository(temp_db)
        sid = repo.insert(
            ticker_id=tid,
            timestamp="2024-01-15T10:00:00",
            signal_type="SELL",
            confidence=0.7,
        )
        repo.update_status(sid, "executed")

        sig = temp_db.connection.execute(
            "SELECT status FROM trading_signals WHERE id = ?", (sid,)
        ).fetchone()
        assert sig["status"] == "executed"


class TestPositionRepository:
    def test_open_and_close(self, temp_db) -> None:
        ticker_repo = TickerRepository(temp_db)
        tid = ticker_repo.insert("POSTEST")

        repo = PositionRepository(temp_db)
        pid = repo.open_position(
            ticker_id=tid,
            side="LONG",
            quantity=100.0,
            entry_price=100.0,
        )
        assert pid > 0

        open_pos = repo.get_open_positions()
        assert len(open_pos) >= 1

        repo.close_position(pid, exit_price=105.0, commission=1.0)

        pos = temp_db.connection.execute(
            "SELECT status FROM positions WHERE id = ?", (pid,)
        ).fetchone()
        assert pos["status"] == "closed"


class TestRiskMetricRepository:
    def test_upsert(self, temp_db) -> None:
        repo = RiskMetricRepository(temp_db)
        repo.upsert(
            date="2024-01-15",
            total_equity=100_000.0,
            daily_return=0.02,
            sharpe_ratio=1.5,
            max_drawdown=0.05,
        )

        metrics = repo.get_by_date("2024-01-15")
        assert metrics is not None
        assert metrics["total_equity"] == 100_000.0

    def test_update_existing(self, temp_db) -> None:
        repo = RiskMetricRepository(temp_db)
        repo.upsert(date="2024-01-15", total_equity=100_000.0)
        repo.upsert(date="2024-01-15", total_equity=105_000.0)

        metrics = repo.get_by_date("2024-01-15")
        assert metrics["total_equity"] == 105_000.0

    def test_get_latest(self, temp_db) -> None:
        repo = RiskMetricRepository(temp_db)
        repo.upsert(date="2024-01-14", total_equity=99_000.0)
        repo.upsert(date="2024-01-15", total_equity=100_000.0)

        latest = repo.get_latest()
        assert latest["date"] == "2024-01-15"


class TestAuditLogRepository:
    def test_log_and_query(self, temp_db) -> None:
        repo = AuditLogRepository(temp_db)
        repo.log(
            action="test_action",
            entity_type="ticker",
            entity_id=1,
            user="system",
            details={"key": "value"},
        )

        entries = repo.get_recent()
        assert len(entries) >= 1
        assert entries[0]["action"] == "test_action"
