"""Shared pytest fixtures for all tests."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest

from pipeline.config import (
    DatabaseConfig,
    PipelineConfig,
    RiskConfig,
    SinkConfig,
    SourceConfig,
    TransformerConfig,
)
from pipeline.database.connection import DatabaseConnection


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Generate sample OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(100)],
            "High": [105.0 + i * 0.1 for i in range(100)],
            "Low": [99.0 + i * 0.1 for i in range(100)],
            "Close": [104.0 + i * 0.1 for i in range(100)],
            "Volume": [1_000_000 + i * 1000 for i in range(100)],
            "Ticker": ["TEST"] * 100,
        },
        index=dates,
    )


@pytest.fixture
def sample_ohlcv_with_nan() -> pd.DataFrame:
    """Generate OHLCV DataFrame with missing values."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    df = pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(100)],
            "High": [105.0 + i * 0.1 for i in range(100)],
            "Low": [99.0 + i * 0.1 for i in range(100)],
            "Close": [104.0 + i * 0.1 for i in range(100)],
            "Volume": [1_000_000 + i * 1000 for i in range(100)],
            "Ticker": ["TEST"] * 100,
        },
        index=dates,
    )
    df.iloc[10, 0] = pd.NA  # NaN in Open
    df.iloc[20, 3] = pd.NA  # NaN in Close
    df.iloc[30, 4] = pd.NA  # NaN in Volume
    return df


@pytest.fixture
def temp_db() -> Generator[DatabaseConnection, None, None]:
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    config = DatabaseConfig(database_path=db_path)
    db = DatabaseConnection(config)
    db.connect()
    db.initialize_schema(Path("schema.sql"))

    yield db

    db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def test_config() -> PipelineConfig:
    """Create a test pipeline configuration."""
    return PipelineConfig(
        source=SourceConfig(
            source_type="yahoo_finance",
            tickers=["AAPL", "GOOGL"],
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            timeframe="1d",
        ),
        transform=TransformerConfig(
            transformers=["missing_value_cleaner", "feature_engineer"],
            feature_window=20,
        ),
        sink=SinkConfig(
            sink_type="sqlite",
            output_path="./data/processed",
            database_path="./data/test.db",
        ),
        database=DatabaseConfig(database_path="./data/test.db"),
        risk=RiskConfig(),
        log_level="WARNING",
    )
