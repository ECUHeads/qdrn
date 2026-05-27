"""
Abstract Sink — Base class for all data loading destinations.

Defines the contract that all sink implementations must follow,
supporting Parquet, SQLite, Redis, and other storage backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from pipeline.config import SinkConfig
from pipeline.events.bus import ObserverBus
from pipeline.logging import get_logger


@dataclass(frozen=True)
class LoadResult:
    """Immutable result of a load operation."""
    rows_written: int
    bytes_written: int
    partition_key: str


class AbstractSink(ABC):
    """Abstract base class for all data sinks."""

    def __init__(
        self,
        config: SinkConfig,
        observer_bus: Optional[ObserverBus] = None,
    ) -> None:
        self.config = config
        self.observer_bus = observer_bus
        self.logger = get_logger(
            f"{self.__class__.__module__}.{self.__class__.__name__}",
            component=self.__class__.__name__,
        )

    @abstractmethod
    def load(self, df: pd.DataFrame, partition_key: str) -> LoadResult:
        """Persist DataFrame to storage backend."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources (connections, file handles)."""
        ...

    def _emit_event(self, event_type: str, payload: dict) -> None:
        """Emit pipeline event to observer bus."""
        if self.observer_bus:
            self.observer_bus.emit(event_type, payload)
