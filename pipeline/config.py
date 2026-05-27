"""
Pipeline Configuration — Type-safe dataclass definitions.

All configuration is centralized here with frozen dataclasses for immutability
and type safety. Supports YAML loading and environment variable overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for data extraction sources."""

    source_type: str  # "yahoo_finance", "csv", "sql", "rest_api"
    tickers: List[str]
    start_date: datetime
    end_date: datetime
    timeframe: str = "1d"
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    retry_base_delay: float = 2.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        assert self.source_type in (
            "yahoo_finance",
            "csv",
            "sql",
            "rest_api",
        ), f"Unsupported source type: {self.source_type}"
        assert self.timeframe in (
            "1m",
            "5m",
            "15m",
            "30m",
            "60m",
            "1d",
            "1wk",
            "1mo",
        ), f"Unsupported timeframe: {self.timeframe}"
        assert len(self.tickers) > 0, "At least one ticker is required"


@dataclass(frozen=True)
class TransformerConfig:
    """Configuration for data transformation pipeline."""

    transformers: List[str] = field(default_factory=list)
    feature_window: int = 60
    normalization_range: Tuple[float, float] = (0.0, 1.0)
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14


@dataclass(frozen=True)
class SinkConfig:
    """Configuration for data loading sinks."""

    sink_type: str  # "parquet", "sqlite", "redis"
    output_path: str
    partition_by: List[str] = field(default_factory=list)
    compression: str = "snappy"
    database_path: str = "data/drl_trading.db"

    def __post_init__(self) -> None:
        assert self.sink_type in (
            "parquet",
            "sqlite",
            "redis",
        ), f"Unsupported sink type: {self.sink_type}"


@dataclass(frozen=True)
class DatabaseConfig:
    """Configuration for SQLite database connection."""

    database_path: str = "data/drl_trading.db"
    pool_size: int = 5
    timeout: float = 30.0
    wal_mode: bool = True
    foreign_keys: bool = True
    busy_timeout: int = 5000


@dataclass(frozen=True)
class RiskConfig:
    """Configuration for risk management module."""

    max_drawdown_limit: float = 0.15
    max_position_size: float = 0.10
    max_leverage: float = 1.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_open_positions: int = 10


@dataclass(frozen=True)
class PipelineConfig:
    """Master configuration for the entire data pipeline."""

    source: SourceConfig
    transform: TransformerConfig = field(default_factory=TransformerConfig)
    sink: SinkConfig = field(default_factory=lambda: SinkConfig(
        sink_type="sqlite", output_path="data/processed"
    ))
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    log_level: str = "INFO"
    enable_metrics: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> PipelineConfig:
        """Load configuration from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> PipelineConfig:
        """Build PipelineConfig from nested dictionary."""
        pipeline_cfg = data.get("pipeline", {})
        source_data = data.get("source", {})
        transform_data = data.get("transform", {})
        sink_data = data.get("sink", {})
        db_data = data.get("database", {})
        risk_data = data.get("risk", {})

        # Parse dates
        if "start_date" in source_data and isinstance(source_data["start_date"], str):
            source_data["start_date"] = datetime.fromisoformat(source_data["start_date"])
        if "end_date" in source_data and isinstance(source_data["end_date"], str):
            source_data["end_date"] = datetime.fromisoformat(source_data["end_date"])

        # Convert normalization_range list to tuple for frozen dataclass compatibility
        transform_data = transform_data.copy() if transform_data else {}
        if "normalization_range" in transform_data and isinstance(
            transform_data["normalization_range"], list
        ):
            transform_data["normalization_range"] = tuple(transform_data["normalization_range"])

        source = SourceConfig(**source_data)
        transform = TransformerConfig(**transform_data)
        sink = SinkConfig(**sink_data)
        database = DatabaseConfig(**db_data) if db_data else DatabaseConfig()
        risk = RiskConfig(**risk_data) if risk_data else RiskConfig()

        return cls(
            source=source,
            transform=transform,
            sink=sink,
            database=database,
            risk=risk,
            log_level=pipeline_cfg.get("log_level", "INFO"),
            enable_metrics=pipeline_cfg.get("enable_metrics", True),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "source": {
                "source_type": self.source.source_type,
                "tickers": self.source.tickers,
                "start_date": self.source.start_date.isoformat(),
                "end_date": self.source.end_date.isoformat(),
                "timeframe": self.source.timeframe,
                "rate_limit_delay": self.source.rate_limit_delay,
                "max_retries": self.source.max_retries,
                "retry_base_delay": self.source.retry_base_delay,
            },
            "transform": {
                "transformers": self.transform.transformers,
                "feature_window": self.transform.feature_window,
            },
            "sink": {
                "sink_type": self.sink.sink_type,
                "output_path": self.sink.output_path,
            },
            "pipeline": {
                "log_level": self.log_level,
                "enable_metrics": self.enable_metrics,
            },
        }
