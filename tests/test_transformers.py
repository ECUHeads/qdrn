"""Tests for transformer components."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.config import TransformerConfig
from pipeline.transform.base import AbstractTransformer, TransformerChain
from pipeline.transform.transformers.cleaner import MissingValueCleaner
from pipeline.transform.transformers.feature_engineer import TechnicalFeatureEngineer
from pipeline.transform.transformers.normalizer import MinMaxNormalizer


class TestMissingValueCleaner:
    def test_fill_nan_values(self, sample_ohlcv_with_nan: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        cleaner = MissingValueCleaner(config=cfg)
        result = cleaner.transform(sample_ohlcv_with_nan)
        assert result.isna().sum().sum() == 0

    def test_preserves_row_count(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        cleaner = MissingValueCleaner(config=cfg)
        result = cleaner.transform(sample_ohlcv)
        assert len(result) == len(sample_ohlcv)

    def test_get_name(self) -> None:
        cfg = TransformerConfig()
        cleaner = MissingValueCleaner(config=cfg)
        assert cleaner.get_name() == "MissingValueCleaner"

    def test_empty_dataframe_raises(self) -> None:
        cfg = TransformerConfig()
        cleaner = MissingValueCleaner(config=cfg)
        with pytest.raises(ValueError, match="empty"):
            cleaner.transform(pd.DataFrame())


class TestTechnicalFeatureEngineer:
    def test_creates_feature_columns(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        result = engineer.transform(sample_ohlcv)

        expected_cols = [
            "rsi_14", "macd_12_26", "macd_signal", "macd_histogram",
            "bb_upper", "bb_lower", "bb_middle", "atr_14",
            "rolling_return_5", "rolling_return_20", "rolling_vol_20",
            "volume_sma_20", "volume_ratio",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_rsi_range(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        result = engineer.transform(sample_ohlcv)
        valid_rsi = result["rsi_14"].dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_preserves_row_count(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        result = engineer.transform(sample_ohlcv)
        assert len(result) == len(sample_ohlcv)

    def test_get_name(self) -> None:
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        assert "FeatureEngineer" in engineer.get_name()


class TestMinMaxNormalizer:
    def test_normalized_columns_created(self, sample_ohlcv: pd.DataFrame) -> None:
        # First add some features to normalize
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        df_with_features = engineer.transform(sample_ohlcv)

        normalizer = MinMaxNormalizer(config=cfg)
        result = normalizer.transform(df_with_features)

        # Check that normalized columns exist
        norm_cols = [c for c in result.columns if c.startswith("normalized_")]
        assert len(norm_cols) > 0

    def test_normalized_values_range(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        engineer = TechnicalFeatureEngineer(config=cfg)
        df_with_features = engineer.transform(sample_ohlcv)

        normalizer = MinMaxNormalizer(config=cfg)
        result = normalizer.transform(df_with_features)

        norm_cols = [c for c in result.columns if c.startswith("normalized_")]
        for col in norm_cols:
            values = result[col].dropna()
            assert (values >= -0.01).all(), f"Values below 0 in {col}"
            assert (values <= 1.01).all(), f"Values above 1 in {col}"

    def test_get_name(self) -> None:
        cfg = TransformerConfig()
        normalizer = MinMaxNormalizer(config=cfg)
        assert normalizer.get_name() == "MinMaxNormalizer"


class TestTransformerChain:
    def test_chain_executes_all(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        chain = TransformerChain(
            transformers=[
                MissingValueCleaner(config=cfg),
                TechnicalFeatureEngineer(config=cfg),
            ],
            config=cfg,
        )
        result = chain.transform(sample_ohlcv)
        assert "rsi_14" in result.columns

    def test_chain_add_transformer(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        chain = TransformerChain(config=cfg)
        chain.add(MissingValueCleaner(config=cfg))
        chain.add(TechnicalFeatureEngineer(config=cfg))

        result = chain.transform(sample_ohlcv)
        assert "rsi_14" in result.columns

    def test_chain_name(self) -> None:
        cfg = TransformerConfig()
        chain = TransformerChain(
            transformers=[
                MissingValueCleaner(config=cfg),
                MinMaxNormalizer(config=cfg),
            ],
            config=cfg,
        )
        name = chain.get_name()
        assert "MissingValueCleaner" in name
        assert "MinMaxNormalizer" in name

    def test_empty_chain(self, sample_ohlcv: pd.DataFrame) -> None:
        cfg = TransformerConfig()
        chain = TransformerChain(config=cfg)
        result = chain.transform(sample_ohlcv)
        assert len(result) == len(sample_ohlcv)
