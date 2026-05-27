"""
Abstract Transformer — Base class for all data transformations.

Implements the Strategy pattern: each transformer is an interchangeable
strategy that can be composed into a chain via TransformerChain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd

from pipeline.config import TransformerConfig
from pipeline.events.bus import ObserverBus
from pipeline.logging import get_logger


class AbstractTransformer(ABC):
    """Abstract base class for all data transformers."""

    def __init__(
        self,
        config: TransformerConfig,
        observer_bus: Optional[ObserverBus] = None,
    ) -> None:
        self.config = config
        self.observer_bus = observer_bus
        self.logger = get_logger(
            f"{self.__class__.__module__}.{self.__class__.__name__}",
            component=self.__class__.__name__,
        )

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply transformation to input DataFrame."""
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Return transformer identifier name."""
        ...

    def _validate_input(self, df: pd.DataFrame) -> None:
        """Validate that input DataFrame is not empty."""
        if df.empty:
            raise ValueError("Input DataFrame is empty")

    def _emit_event(self, event_type: str, payload: dict) -> None:
        """Emit pipeline event to observer bus."""
        if self.observer_bus:
            self.observer_bus.emit(event_type, payload)


class TransformerChain(AbstractTransformer):
    """Composite transformer that chains multiple strategies sequentially."""

    def __init__(
        self,
        transformers: Optional[List[AbstractTransformer]] = None,
        config: Optional[TransformerConfig] = None,
        observer_bus: Optional[ObserverBus] = None,
    ) -> None:
        super().__init__(config or TransformerConfig(), observer_bus)
        self._transformers: List[AbstractTransformer] = transformers or []

    def add(self, transformer: AbstractTransformer) -> None:
        """Add a transformer to the chain."""
        self._transformers.append(transformer)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Execute all transformers in order."""
        self._emit_event("TRANSFORM_STARTED", {
            "transformers": [t.get_name() for t in self._transformers],
            "input_rows": len(df),
        })

        result = df.copy()
        for transformer in self._transformers:
            self.logger.debug("Applying transformer: %s", transformer.get_name())
            result = transformer.transform(result)

        self._emit_event("TRANSFORM_COMPLETED", {
            "output_rows": len(result),
            "transformers_applied": [t.get_name() for t in self._transformers],
        })
        return result

    def get_name(self) -> str:
        """Return composite name of all transformers in chain."""
        names = [t.get_name() for t in self._transformers]
        return f"Chain:{','.join(names)}"
