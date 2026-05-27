"""
Technical Feature Engineer — Computes technical indicators for RL state input.

Generates RSI, MACD, Bollinger Bands, ATR, Rolling Returns, and Volume metrics
as features for the Deep Reinforcement Learning agent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import TransformerConfig
from pipeline.events.bus import ObserverBus
from pipeline.transform.base import AbstractTransformer


class TechnicalFeatureEngineer(AbstractTransformer):
    """Compute technical analysis features from OHLCV data."""

    def __init__(
        self,
        config: TransformerConfig,
        observer_bus: ObserverBus | None = None,
    ) -> None:
        super().__init__(config, observer_bus)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicator columns to DataFrame."""
        self._validate_input(df)
        result = df.copy()

        close = result["Close"]
        high = result["High"]
        low = result["Low"]
        volume = result["Volume"]

        # RSI (Relative Strength Index)
        rsi_period = self.config.rsi_period
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=rsi_period, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=rsi_period, min_periods=1).mean()
        rs = gain / loss.replace(0, np.nan)
        result["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD (Moving Average Convergence Divergence)
        ema_fast = close.ewm(span=self.config.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.config.macd_slow, adjust=False).mean()
        result["macd_12_26"] = ema_fast - ema_slow
        result["macd_signal"] = result["macd_12_26"].ewm(
            span=self.config.macd_signal, adjust=False
        ).mean()
        result["macd_histogram"] = result["macd_12_26"] - result["macd_signal"]

        # Bollinger Bands
        bb_period = self.config.bb_period
        sma = close.rolling(window=bb_period, min_periods=1).mean()
        std = close.rolling(window=bb_period, min_periods=1).std()
        result["bb_upper"] = sma + self.config.bb_std * std
        result["bb_lower"] = sma - self.config.bb_std * std
        result["bb_middle"] = sma

        # ATR (Average True Range)
        atr_period = self.config.atr_period
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        result["atr_14"] = true_range.rolling(window=atr_period, min_periods=1).mean()

        # Rolling Returns
        result["rolling_return_5"] = close.pct_change(periods=5)
        result["rolling_return_20"] = close.pct_change(periods=20)

        # Rolling Volatility
        result["rolling_vol_20"] = close.pct_change().rolling(
            window=20, min_periods=1
        ).std()

        # Volume Features
        result["volume_sma_20"] = volume.rolling(window=20, min_periods=1).mean()
        result["volume_ratio"] = volume / result["volume_sma_20"].replace(0, np.nan)

        self.logger.info(
            "Engineered %d feature columns for %d rows",
            len(self._feature_columns()),
            len(result),
        )
        return result

    def get_name(self) -> str:
        return "TechnicalFeatureEngineer"

    def _feature_columns(self) -> list[str]:
        return [
            "rsi_14", "macd_12_26", "macd_signal", "macd_histogram",
            "bb_upper", "bb_lower", "bb_middle", "atr_14",
            "rolling_return_5", "rolling_return_20", "rolling_vol_20",
            "volume_sma_20", "volume_ratio",
        ]
