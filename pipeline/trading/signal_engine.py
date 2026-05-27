"""
Signal Engine — Rule-based trading signal generator.

Generates BUY/SELL/HOLD signals based on technical indicator thresholds.
Serves as a baseline before deploying the RL agent for signal generation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from pipeline.config import RiskConfig
from pipeline.database.connection import DatabaseConnection
from pipeline.database.repository import (
    AuditLogRepository,
    MarketDataRepository,
    TickerRepository,
    TradingSignalRepository,
)
from pipeline.errors import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Represents a single trading signal."""
    ticker: str
    signal_type: str  # "BUY" | "SELL" | "HOLD"
    confidence: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: Optional[float] = None
    features: Dict[str, float] = field(default_factory=dict)


class SignalEngine:
    """Generate trading signals from technical indicators."""

    def __init__(
        self,
        db: DatabaseConnection,
        risk_config: RiskConfig | None = None,
    ) -> None:
        self._db = db
        self._ticker_repo = TickerRepository(db)
        self._market_repo = MarketDataRepository(db)
        self._signal_repo = TradingSignalRepository(db)
        self._audit_repo = AuditLogRepository(db)
        self._risk_config = risk_config or RiskConfig()

    def generate_signals(
        self, tickers: Optional[List[str]] = None
    ) -> List[Signal]:
        """Generate signals for all active tickers or specified list."""
        if tickers:
            ticker_list = tickers
        else:
            ticker_list = [
                t["symbol"]
                for t in self._ticker_repo.get_all_active()
            ]

        signals: List[Signal] = []

        for symbol in ticker_list:
            ticker_id = self._ticker_repo.get_by_symbol(symbol)
            if ticker_id is None:
                logger.warning("Ticker not found: %s", symbol)
                continue

            latest = self._market_repo.latest(ticker_id)
            if latest is None:
                logger.warning("No market data for %s", symbol)
                continue

            signal = self._evaluate(latest, symbol)
            signals.append(signal)

            # Persist signal to database
            self._persist_signal(signal, ticker_id)

        logger.info("Generated %d signals for %d tickers", len(signals), len(ticker_list))
        return signals

    def _evaluate(self, data: Dict, symbol: str) -> Signal:
        """Evaluate technical indicators and produce a signal."""
        features = {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
        close = data.get("close", 0)

        # Simple rule-based evaluation using available indicators
        score = 0.0

        # RSI-based momentum
        rsi = features.get("rsi_14", 50)
        if rsi < 30:
            score += 0.3  # Oversold → Buy signal
        elif rsi > 70:
            score -= 0.3  # Overbought → Sell signal

        # MACD crossover
        macd = features.get("macd_12_26", 0)
        macd_sig = features.get("macd_signal", 0)
        if macd > macd_sig and macd > 0:
            score += 0.2
        elif macd < macd_sig and macd < 0:
            score -= 0.2

        # Bollinger Band position
        bb_upper = features.get("bb_upper", close * 1.1)
        bb_lower = features.get("bb_lower", close * 0.9)
        if close <= bb_lower:
            score += 0.2
        elif close >= bb_upper:
            score -= 0.2

        # Determine signal type
        if score >= 0.3:
            signal_type = "BUY"
            confidence = min(abs(score) + 0.3, 1.0)
        elif score <= -0.3:
            signal_type = "SELL"
            confidence = min(abs(score) + 0.3, 1.0)
        else:
            signal_type = "HOLD"
            confidence = max(0.5, 1.0 - abs(score))

        # Calculate stop loss and take profit
        stop_loss = round(close * (1 - self._risk_config.stop_loss_pct), 2) if signal_type == "BUY" else round(close * (1 + self._risk_config.stop_loss_pct), 2)
        take_profit = round(close * (1 + self._risk_config.take_profit_pct), 2) if signal_type == "BUY" else round(close * (1 - self._risk_config.take_profit_pct), 2)

        return Signal(
            ticker=symbol,
            signal_type=signal_type,
            confidence=round(confidence, 4),
            entry_price=close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=self._risk_config.max_position_size if signal_type != "HOLD" else None,
            features={k: round(v, 6) for k, v in features.items()},
        )

    def _persist_signal(self, signal: Signal, ticker_id: int) -> None:
        """Save signal to database and audit log."""
        ts = self._market_repo.latest(ticker_id)
        timestamp = ts.get("timestamp", "") if ts else ""

        signal_id = self._signal_repo.insert(
            ticker_id=ticker_id,
            timestamp=timestamp,
            signal_type=signal.signal_type,
            confidence=signal.confidence,
            position_size=signal.position_size,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            features_json=json.dumps(signal.features),
        )

        self._audit_repo.log(
            action="signal_generated",
            entity_type="trading_signal",
            entity_id=signal_id,
            details={
                "ticker": signal.ticker,
                "type": signal.signal_type,
                "confidence": signal.confidence,
            },
        )
