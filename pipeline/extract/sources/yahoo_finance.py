"""
Yahoo Finance Data Source.

Extracts OHLCV data from Yahoo Finance via the yfinance library with
rate limiting, retry logic, and schema validation.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd

from pipeline.config import SourceConfig
from pipeline.errors import ExtractionError, SchemaValidationError
from pipeline.events.bus import ObserverBus
from pipeline.extract.sources.base import AbstractDataSource

logger = logging.getLogger(__name__)


class YahooFinanceSource(AbstractDataSource):
    """Data source for Yahoo Finance via yfinance library."""

    SUPPORTED_TIMEFRAMES: List[str] = ["1m", "5m", "15m", "30m", "60m", "1d", "1wk", "1mo"]
    REQUIRED_COLUMNS: List[str] = ["Open", "High", "Low", "Close", "Volume"]

    def __init__(
        self,
        config: SourceConfig,
        observer_bus: Optional[ObserverBus] = None,
        proxy: Optional[str] = None,
    ) -> None:
        super().__init__(config, observer_bus)
        self.proxy = proxy

    def extract(
        self, tickers: List[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Extract OHLCV data for multiple tickers."""
        self._emit_event("EXTRACT_STARTED", {
            "tickers": tickers,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        frames: List[pd.DataFrame] = []

        for i, ticker in enumerate(tickers):
            # Rate limiting between requests
            if i > 0:
                time.sleep(self.config.rate_limit_delay)

            try:
                ticker_obj = self._create_ticker(ticker)
                df = self._with_retry(
                    ticker_obj.history,
                    start=start,
                    end=end,
                    interval=self.config.timeframe,
                    proxy=self.proxy,
                )

                if df.empty:
                    self.logger.warning("No data returned for %s", ticker)
                    continue

                df["Ticker"] = ticker
                frames.append(df.reset_index())

            except Exception as exc:
                self._emit_event("EXTRACT_FAILED", {"error": str(exc), "ticker": ticker})
                self.logger.error("Extraction failed for %s: %s", ticker, exc)
                raise ExtractionError(f"Failed to extract {ticker}", ticker=ticker) from exc

        if not frames:
            raise ExtractionError("No data extracted for any ticker")

        combined = pd.concat(frames, ignore_index=True)

        if not self.validate(combined):
            missing = set(self.REQUIRED_COLUMNS) - set(combined.columns)
            raise SchemaValidationError(
                f"Missing columns: {missing}",
                expected_columns=self.REQUIRED_COLUMNS,
                missing_columns=list(missing),
            )

        self._emit_event("EXTRACT_COMPLETED", {
            "rows_fetched": len(combined),
            "tickers_with_data": [f["Ticker"].iloc[0] for f in frames],
        })

        self.logger.info("Extracted %d rows for %d tickers", len(combined), len(frames))
        return combined

    def validate(self, raw_data: pd.DataFrame) -> bool:
        """Validate that required OHLCV columns are present."""
        missing = set(self.REQUIRED_COLUMNS) - set(raw_data.columns)
        if missing:
            self.logger.error("Schema validation failed. Missing: %s", missing)
            return False
        return True

    def get_supported_timeframes(self) -> List[str]:
        """Return supported timeframe intervals."""
        return list(self.SUPPORTED_TIMEFRAMES)

    def _create_ticker(self, ticker: str):
        """Create a yfinance Ticker object (lazy import)."""
        import yfinance as yf  # noqa: PLC0414
        return yf.Ticker(ticker)
