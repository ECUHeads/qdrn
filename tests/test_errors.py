"""Tests for exception hierarchy."""

from __future__ import annotations

import pytest

from pipeline.errors import (
    ConfigurationError,
    DatabaseError,
    ExtractionError,
    LoadError,
    PipelineError,
    RetryExhaustedError,
    RiskLimitExceededError,
    SchemaValidationError,
    SourceNotFoundError,
    TransformationError,
)


class TestPipelineError:
    def test_base_error_message(self) -> None:
        err = PipelineError("test error")
        assert "test error" in str(err)

    def test_base_error_with_context(self) -> None:
        err = PipelineError("test", context={"key": "val"})
        assert "key=val" in str(err)


class TestSourceNotFoundError:
    def test_message(self) -> None:
        err = SourceNotFoundError("bad_source", available=["a", "b"])
        assert "bad_source" in str(err)
        assert "a" in str(err) or "available" in str(err).lower()

    def test_attributes(self) -> None:
        err = SourceNotFoundError("x")
        assert err.source_type == "x"


class TestExtractionError:
    def test_with_ticker(self) -> None:
        err = ExtractionError("fail", ticker="AAPL")
        assert err.ticker == "AAPL"


class TestRetryExhaustedError:
    def test_attributes(self) -> None:
        err = RetryExhaustedError("done", attempts=3)
        assert err.attempts == 3


class TestTransformationError:
    def test_with_transformer(self) -> None:
        err = TransformationError("bad transform", transformer_name="Cleaner")
        assert err.transformer_name == "Cleaner"


class TestSchemaValidationError:
    def test_with_columns(self) -> None:
        err = SchemaValidationError(
            "missing",
            expected_columns=["A", "B"],
            missing_columns=["B"],
        )
        assert err.missing_columns == ["B"]


class TestLoadError:
    def test_attributes(self) -> None:
        err = LoadError("write fail", sink_type="sqlite")
        assert err.sink_type == "sqlite"


class TestDatabaseError:
    def test_with_operation(self) -> None:
        err = DatabaseError("conn fail", operation="connect")
        assert err.operation == "connect"


class TestRiskLimitExceededError:
    def test_attributes(self) -> None:
        err = RiskLimitExceededError(
            "over limit",
            limit_type="drawdown",
            current_value=0.2,
            limit_value=0.15,
        )
        assert err.limit_type == "drawdown"
        assert err.current_value == 0.2


class TestConfigurationError:
    def test_with_field(self) -> None:
        err = ConfigurationError("bad config", field="tickers")
        assert err.field == "tickers"
