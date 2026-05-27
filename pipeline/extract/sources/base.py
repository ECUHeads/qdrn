"""
Abstract Data Source — Base class for all data extraction sources.

Implements the Open/Closed Principle: extend by subclassing,
never modify existing implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Optional

import pandas as pd

from pipeline.config import SourceConfig
from pipeline.events.bus import ObserverBus
from pipeline.logging import get_logger
from pipeline.retry import RetryMechanism


class AbstractDataSource(ABC):
    """Abstract base class for all data sources."""

    def __init__(
        self,
        config: SourceConfig,
        observer_bus: Optional[ObserverBus] = None,
    ) -> None:
        self.config = config
        self.observer_bus = observer_bus
        self.logger = get_logger(
            f"{self.__class__.__module__}.{self.__class__.__name__}",
            component=self.__class__.__name__,
        )

    @abstractmethod
    def extract(
        self, tickers: List[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Extract raw OHLCV data for given tickers and date range."""
        ...

    @abstractmethod
    def validate(self, raw_data: pd.DataFrame) -> bool:
        """Validate extracted data against expected schema."""
        ...

    @abstractmethod
    def get_supported_timeframes(self) -> List[str]:
        """Return list of supported timeframe intervals."""
        ...

    def _with_retry(self, func, *args: Any, **kwargs: Any) -> Any:
        """Execute function with exponential backoff retry."""
        retry = RetryMechanism(
            max_retries=self.config.max_retries,
            base_delay=self.config.retry_base_delay,
        )
        return retry.execute(func, *args, **kwargs)

    def _emit_event(self, event_type: str, payload: dict) -> None:
        """Emit pipeline event to observer bus."""
        if self.observer_bus:
            self.observer_bus.emit(event_type, payload)
