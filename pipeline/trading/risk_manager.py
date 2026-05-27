"""
Risk Manager — Enforces risk limits and position constraints.

Validates trading actions against configured risk parameters including
max drawdown, position size limits, leverage caps, and open position counts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pipeline.config import RiskConfig
from pipeline.database.connection import DatabaseConnection
from pipeline.database.repository import (
    AuditLogRepository,
    PositionRepository,
    RiskMetricRepository,
)
from pipeline.errors import RiskLimitExceededError

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforce risk limits on trading operations."""

    def __init__(
        self,
        db: DatabaseConnection,
        config: RiskConfig | None = None,
    ) -> None:
        self._db = db
        self._config = config or RiskConfig()
        self._position_repo = PositionRepository(db)
        self._risk_repo = RiskMetricRepository(db)
        self._audit_repo = AuditLogRepository(db)

    def validate_new_position(
        self,
        ticker_id: int,
        side: str,
        quantity: float,
        entry_price: float,
        current_equity: float,
    ) -> bool:
        """Validate that a new position does not violate risk limits.

        Returns:
            True if the position is allowed.

        Raises:
            RiskLimitExceededError: If any risk limit would be violated.
        """
        position_value = quantity * entry_price

        # Check max position size as % of equity
        position_pct = position_value / current_equity if current_equity > 0 else float("inf")
        if position_pct > self._config.max_position_size:
            raise RiskLimitExceededError(
                f"Position size {position_pct:.2%} exceeds max {self._config.max_position_size:.2%}",
                limit_type="max_position_size",
                current_value=position_pct,
                limit_value=self._config.max_position_size,
            )

        # Check max open positions
        open_positions = self._position_repo.get_open_positions()
        if len(open_positions) >= self._config.max_open_positions:
            raise RiskLimitExceededError(
                f"Open positions ({len(open_positions)}) at limit ({self._config.max_open_positions})",
                limit_type="max_open_positions",
                current_value=len(open_positions),
                limit_value=self._config.max_open_positions,
            )

        # Check current drawdown
        latest_risk = self._risk_repo.get_latest()
        if latest_risk:
            current_dd = latest_risk.get("current_drawdown", 0) or 0
            if current_dd >= self._config.max_drawdown_limit:
                raise RiskLimitExceededError(
                    f"Current drawdown {current_dd:.2%} exceeds max {self._config.max_drawdown_limit:.2%}",
                    limit_type="max_drawdown",
                    current_value=current_dd,
                    limit_value=self._config.max_drawdown_limit,
                )

        logger.info("Position validated: %s %.0f @ %.2f", side, quantity, entry_price)
        return True

    def check_drawdown(self, current_equity: float, peak_equity: float) -> Dict[str, float]:
        """Calculate current drawdown metrics.

        Returns:
            Dictionary with drawdown percentage and status.
        """
        if peak_equity <= 0:
            return {"drawdown_pct": 0.0, "is_breached": False}

        drawdown_pct = (peak_equity - current_equity) / peak_equity
        is_breached = drawdown_pct >= self._config.max_drawdown_limit

        if is_breached:
            logger.warning(
                "Drawdown limit breached: %.2f%% >= %.2f%%",
                drawdown_pct * 100,
                self._config.max_drawdown_limit * 100,
            )
            self._audit_repo.log(
                action="drawdown_breached",
                entity_type="risk",
                details={
                    "drawdown_pct": drawdown_pct,
                    "limit": self._config.max_drawdown_limit,
                    "current_equity": current_equity,
                    "peak_equity": peak_equity,
                },
            )

        return {
            "drawdown_pct": drawdown_pct,
            "is_breached": is_breached,
            "current_equity": current_equity,
            "peak_equity": peak_equity,
        }

    def update_daily_metrics(
        self,
        total_equity: float,
        daily_return: float = 0.0,
        sharpe_ratio: Optional[float] = None,
        max_drawdown: float = 0.0,
        current_drawdown: float = 0.0,
        win_rate: float = 0.0,
        total_trades: int = 0,
        winning_trades: int = 0,
    ) -> None:
        """Record daily risk metrics."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._risk_repo.upsert(
            date=today,
            total_equity=total_equity,
            daily_return=daily_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            win_rate=win_rate,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=total_trades - winning_trades,
        )
        logger.info("Updated daily risk metrics for %s", today)

    def get_risk_summary(self) -> Dict[str, object]:
        """Get current risk summary."""
        latest = self._risk_repo.get_latest()
        open_positions = self._position_repo.get_open_positions()

        return {
            "config": {
                "max_drawdown_limit": self._config.max_drawdown_limit,
                "max_position_size": self._config.max_position_size,
                "max_leverage": self._config.max_leverage,
                "max_open_positions": self._config.max_open_positions,
            },
            "current_risk": latest or {},
            "open_positions_count": len(open_positions),
            "open_positions": open_positions,
        }
