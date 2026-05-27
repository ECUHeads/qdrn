"""
Sequence Aligner — Creates fixed-length sliding windows for RL state input.

Converts tabular feature data into sequence format suitable for
recurrent or convolutional neural networks in the RL agent.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from pipeline.config import TransformerConfig
from pipeline.events.bus import ObserverBus
from pipeline.transform.base import AbstractTransformer


class SequenceAligner(AbstractTransformer):
    """Create fixed-length sliding windows from feature DataFrame."""

    def __init__(
        self,
        config: TransformerConfig,
        observer_bus: Optional[ObserverBus] = None,
        window_size: int = 60,
        feature_columns: Optional[List[str]] = None,
    ) -> None:
        super().__init__(config, observer_bus)
        self.window_size = window_size
        self.feature_columns = feature_columns or []

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame ready for sequence extraction."""
        self._validate_input(df)
        result = df.copy()

        # Auto-detect normalized feature columns if not specified
        if not self.feature_columns:
            self.feature_columns = [
                col for col in result.columns if col.startswith("normalized_")
            ]

        if not self.feature_columns:
            self.logger.warning("No feature columns found for sequence alignment")
            return result

        # Mark rows that have enough history for a full window
        result["_sequence_ready"] = True
        result.iloc[: self.window_size - 1, result.columns.get_loc("_sequence_ready")] = False

        ready_count = result["_sequence_ready"].sum()
        self.logger.info(
            "Sequence alignment complete: %d/%d rows ready (window=%d)",
            ready_count,
            len(result),
            self.window_size,
        )
        return result

    def get_sequences(self, df: pd.DataFrame) -> np.ndarray:
        """Extract sliding window sequences as numpy array.

        Returns:
            Array of shape (n_sequences, window_size, n_features)
        """
        features = df[self.feature_columns].values
        sequences = []
        for i in range(self.window_size - 1, len(features)):
            window = features[i - self.window_size + 1 : i + 1]
            sequences.append(window)
        return np.array(sequences)

    def get_name(self) -> str:
        return "SequenceAligner"
