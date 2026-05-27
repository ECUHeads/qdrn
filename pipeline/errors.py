"""
Exception Hierarchy for DRL Trading Pipeline.

All exceptions inherit from PipelineError, providing a consistent error
handling contract across all layers of the system.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class PipelineError(Exception):
    """Base exception for all pipeline-related errors."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self.message = message
        self.context = context or {}
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.context:
            ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{ctx}]"
        return self.message


class SourceNotFoundError(PipelineError):
    """Raised when a requested data source type is not registered."""

    def __init__(self, source_type: str, available: Optional[List[str]] = None) -> None:
        self.source_type = source_type
        msg = f"Unknown source type: '{source_type}'"
        if available:
            msg += f". Available: {available}"
        super().__init__(msg, context={"source_type": source_type})


class ExtractionError(PipelineError):
    """Raised when data extraction from a source fails."""

    def __init__(
        self,
        message: str,
        ticker: Optional[str] = None,
        api_response: Optional[str] = None,
    ) -> None:
        self.ticker = ticker
        self.api_response = api_response
        ctx: Dict[str, Any] = {}
        if ticker:
            ctx["ticker"] = ticker
        super().__init__(message, context=ctx)


class RetryExhaustedError(PipelineError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(
        self,
        message: str,
        attempts: int,
        last_exception: Optional[Exception] = None,
    ) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(message, context={"attempts": attempts})


class TransformationError(PipelineError):
    """Raised when a data transformation step fails."""

    def __init__(
        self,
        message: str,
        transformer_name: Optional[str] = None,
        input_shape: Optional[tuple] = None,
    ) -> None:
        self.transformer_name = transformer_name
        self.input_shape = input_shape
        ctx: Dict[str, Any] = {}
        if transformer_name:
            ctx["transformer"] = transformer_name
        if input_shape:
            ctx["input_shape"] = str(input_shape)
        super().__init__(message, context=ctx)


class SchemaValidationError(PipelineError):
    """Raised when extracted data does not match the expected schema."""

    def __init__(
        self,
        message: str,
        expected_columns: Optional[List[str]] = None,
        missing_columns: Optional[List[str]] = None,
    ) -> None:
        self.expected_columns = expected_columns
        self.missing_columns = missing_columns
        ctx: Dict[str, Any] = {}
        if missing_columns:
            ctx["missing"] = missing_columns
        super().__init__(message, context=ctx)


class LoadError(PipelineError):
    """Raised when writing data to a sink fails."""

    def __init__(
        self,
        message: str,
        sink_type: Optional[str] = None,
        partition_key: Optional[str] = None,
    ) -> None:
        self.sink_type = sink_type
        self.partition_key = partition_key
        ctx: Dict[str, Any] = {}
        if sink_type:
            ctx["sink_type"] = sink_type
        if partition_key:
            ctx["partition_key"] = partition_key
        super().__init__(message, context=ctx)


class DatabaseError(PipelineError):
    """Raised when a database operation fails."""

    def __init__(self, message: str, operation: Optional[str] = None) -> None:
        self.operation = operation
        ctx: Dict[str, Any] = {}
        if operation:
            ctx["operation"] = operation
        super().__init__(message, context=ctx)


class RiskLimitExceededError(PipelineError):
    """Raised when a trading action would exceed configured risk limits."""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current_value: float,
        limit_value: float,
    ) -> None:
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value
        super().__init__(
            message,
            context={
                "limit_type": limit_type,
                "current": current_value,
                "limit": limit_value,
            },
        )


class ConfigurationError(PipelineError):
    """Raised when configuration is invalid or incomplete."""

    def __init__(self, message: str, field: Optional[str] = None) -> None:
        self.field = field
        ctx: Dict[str, Any] = {}
        if field:
            ctx["field"] = field
        super().__init__(message, context=ctx)
