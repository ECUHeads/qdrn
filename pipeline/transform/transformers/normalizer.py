"""
MinMax Normalizer — Scales features to [0, 1] range.

Uses rolling window normalization to prevent look-ahead bias in feature scaling.
"""

from __future__ import annotations

import pandas as pd

from pipeline.config import TransformerConfig
from pipeline.events.bus import ObserverBus
from pipeline.transform.base import AbstractTransformer


class MinMaxNormalizer(AbstractTransformer):
    """Normalize numeric columns to [0, 1] using rolling window min/max."""

    def __init__(
        self,
        config: TransformerConfig,
        observer_bus: ObserverBus | None = None,
    ) -> None:
        super().__init__(config, observer_bus)
        self._feature_columns: list[str] = []

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply MinMax normalization to feature columns."""
        self._validate_input(df)
        result = df.copy()

        # Identify numeric feature columns (exclude OHLCV and timestamp/ticker)
        exclude_cols = {"Open", "High", "Low", "Close", "Volume", "Ticker"}
        feature_cols = [
            col for col in result.select_dtypes(include="number").columns
            if col not in exclude_cols
        ]
        self._feature_columns = feature_cols

        window = self.config.feature_window
        target_min, target_max = self.config.normalization_range

        for col in feature_cols:
            rolling_min = result[col].rolling(window=window, min_periods=1).min()
            rolling_max = result[col].rolling(window=window, min_periods=1).max()
            range_ = rolling_max - rolling_min

            # Avoid division by zero
            normalized = (
                ((result[col] - rolling_min) / range_.replace(0, pd.NA))
                .fillna(0.5)  # Default to midpoint when range is zero
            )
            result[f"normalized_{col}"] = normalized

        self.logger.info(
            "Normalized %d feature columns with window=%d",
            len(feature_cols),
            window,
        )
        return result

    def get_name(self) -> str:
        return "MinMaxNormalizer"

    @property
    def feature_columns(self) -> list[str]:
        """Return list of normalized feature column names."""
        return self._feature_columns
