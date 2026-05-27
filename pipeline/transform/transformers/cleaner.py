"""
Missing Value Cleaner — Handles NaN imputation in OHLCV data.

Strategy: Forward-fill then backward-fill to preserve time series continuity
without introducing look-ahead bias.
"""

from __future__ import annotations

import pandas as pd

from pipeline.config import TransformerConfig
from pipeline.events.bus import ObserverBus
from pipeline.transform.base import AbstractTransformer


class MissingValueCleaner(AbstractTransformer):
    """Fill missing values using forward-fill then backward-fill."""

    def __init__(
        self,
        config: TransformerConfig,
        observer_bus: ObserverBus | None = None,
    ) -> None:
        super().__init__(config, observer_bus)
        self._ohlc_columns = ["Open", "High", "Low", "Close", "Volume"]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill NaN values in OHLCV columns."""
        self._validate_input(df)
        result = df.copy()

        nan_before = result.isna().sum().sum()

        # Forward-fill then backward-fill for OHLCV columns
        for col in self._ohlc_columns:
            if col in result.columns:
                result[col] = result[col].ffill().bfill()

        # Fill any remaining NaN with 0 for Volume
        if "Volume" in result.columns:
            result["Volume"] = result["Volume"].fillna(0)

        nan_after = result.isna().sum().sum()
        self.logger.info(
            "Cleaned %d NaN values (%d remaining)", nan_before - nan_after, nan_after
        )
        return result

    def get_name(self) -> str:
        return "MissingValueCleaner"
