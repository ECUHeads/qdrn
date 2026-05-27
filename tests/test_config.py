"""Tests for pipeline configuration module."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from pipeline.config import (
    DatabaseConfig,
    PipelineConfig,
    RiskConfig,
    SinkConfig,
    SourceConfig,
    TransformerConfig,
)


class TestSourceConfig:
    def test_valid_config(self) -> None:
        cfg = SourceConfig(
            source_type="yahoo_finance",
            tickers=["AAPL"],
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        assert cfg.source_type == "yahoo_finance"
        assert cfg.timeframe == "1d"
        assert cfg.max_retries == 3

    def test_invalid_source_type(self) -> None:
        with pytest.raises(AssertionError):
            SourceConfig(
                source_type="invalid",
                tickers=["AAPL"],
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
            )

    def test_empty_tickers(self) -> None:
        with pytest.raises(AssertionError):
            SourceConfig(
                source_type="yahoo_finance",
                tickers=[],
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
            )

    def test_invalid_timeframe(self) -> None:
        with pytest.raises(AssertionError):
            SourceConfig(
                source_type="yahoo_finance",
                tickers=["AAPL"],
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                timeframe="invalid",
            )


class TestTransformerConfig:
    def test_defaults(self) -> None:
        cfg = TransformerConfig()
        assert cfg.feature_window == 60
        assert cfg.normalization_range == (0.0, 1.0)
        assert cfg.rsi_period == 14

    def test_custom_values(self) -> None:
        cfg = TransformerConfig(
            transformers=["cleaner", "engineer"],
            feature_window=30,
        )
        assert cfg.feature_window == 30
        assert len(cfg.transformers) == 2


class TestSinkConfig:
    def test_valid_config(self) -> None:
        cfg = SinkConfig(sink_type="sqlite", output_path="./data")
        assert cfg.sink_type == "sqlite"

    def test_invalid_sink_type(self) -> None:
        with pytest.raises(AssertionError):
            SinkConfig(sink_type="invalid", output_path="./data")


class TestDatabaseConfig:
    def test_defaults(self) -> None:
        cfg = DatabaseConfig()
        assert cfg.wal_mode is True
        assert cfg.foreign_keys is True
        assert cfg.timeout == 30.0


class TestRiskConfig:
    def test_defaults(self) -> None:
        cfg = RiskConfig()
        assert cfg.max_drawdown_limit == 0.15
        assert cfg.max_position_size == 0.10
        assert cfg.max_open_positions == 10


class TestPipelineConfig:
    def test_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = {
            "pipeline": {"log_level": "DEBUG", "enable_metrics": True},
            "source": {
                "source_type": "yahoo_finance",
                "tickers": ["AAPL"],
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
            "transform": {"transformers": ["missing_value_cleaner"]},
            "sink": {"sink_type": "sqlite", "output_path": "./data"},
        }
        yaml_file = tmp_path / "test_config.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(yaml_content, f)

        config = PipelineConfig.from_yaml(yaml_file)
        assert config.log_level == "DEBUG"
        assert config.source.tickers == ["AAPL"]
        assert config.source.start_date == datetime(2024, 1, 1)

    def test_to_dict(self) -> None:
        config = PipelineConfig(
            source=SourceConfig(
                source_type="yahoo_finance",
                tickers=["TEST"],
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
            ),
        )
        d = config.to_dict()
        assert d["source"]["tickers"] == ["TEST"]
        assert "start_date" in d["source"]
