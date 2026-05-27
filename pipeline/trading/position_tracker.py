"""
Position Tracker — Manages position lifecycle and P&L calculation.

Tracks open positions, handles entry/exit execution, and calculates
realized/unrealized P&L with commission and slippage tracking.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from pipeline.database.connection import DatabaseConnection
from pipeline.database.repository import (
    AuditLogRepository,
    PositionRepository,
    TradingSignalRepository,
)
from pipeline.errors import DatabaseError

logger = logging.getLogger(__name__)


class PositionTracker:
    """Track and manage trading positions."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db
        self._position_repo = PositionRepository(db)
        self._signal_repo = TradingSignalRepository(db)
        self._audit_repo = AuditLogRepository(db)

    def open_position(
        self,
        ticker_id: int,
        side: str,
        quantity: float,
        entry_price: float,
        signal_id: Optional[int] = None,
    ) -> int:
        """Open a new position.

        Args:
            ticker_id: Database ID of the ticker.
            side: "LONG" or "SHORT".
            quantity: Number of shares/units.
            entry_price: Price at which position is opened.
            signal_id: Optional reference to triggering signal.

        Returns:
            Position ID in database.
        """
        position_id = self._position_repo.open_position(
            ticker_id=ticker_id,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            signal_id=signal_id,
        )

        # Mark signal as executed
        if signal_id:
            self._signal_repo.update_status(signal_id, "executed")

        self._audit_repo.log(
            action="position_opened",
            entity_type="position",
            entity_id=position_id,
            details={
                "ticker_id": ticker_id,
                "side": side,
                "quantity": quantity,
                "entry_price": entry_price,
            },
        )

        logger.info(
            "Opened position #%d: %s %.0f @ %.2f",
            position_id,
            side,
            quantity,
            entry_price,
        )
        return position_id

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> Dict[str, float]:
        """Close an existing position.

        Returns:
            Dictionary with P&L breakdown.
        """
        positions = self._position_repo.get_open_positions()
        position = next((p for p in positions if p["id"] == position_id), None)

        if not position:
            raise ValueError(f"Position {position_id} not found or already closed")

        quantity = position["quantity"]
        entry_price = position["entry_price"]
        side = position["side"]

        # Calculate P&L
        if side == "LONG":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        net_pnl = gross_pnl - commission - slippage

        self._position_repo.close_position(
            position_id=position_id,
            exit_price=exit_price,
            commission=commission,
            slippage=slippage,
        )

        self._audit_repo.log(
            action="position_closed",
            entity_type="position",
            entity_id=position_id,
            details={
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "commission": commission,
                "slippage": slippage,
            },
        )

        logger.info(
            "Closed position #%d: P&L=%.2f (net=%.2f)",
            position_id,
            gross_pnl,
            net_pnl,
        )

        return {
            "position_id": position_id,
            "gross_pnl": gross_pnl,
            "commission": commission,
            "slippage": slippage,
            "net_pnl": net_pnl,
        }

    def update_position_prices(self, ticker_prices: Dict[int, float]) -> None:
        """Update current market prices for all open positions.

        Args:
            ticker_prices: Mapping of ticker_id → current_price.
        """
        open_positions = self._position_repo.get_open_positions()

        for pos in open_positions:
            ticker_id = pos["ticker_id"]
            if ticker_id in ticker_prices:
                current_price = ticker_prices[ticker_id]
                self._position_repo.update_current_price(pos["id"], current_price)

                # Calculate unrealized P&L
                entry_price = pos["entry_price"]
                quantity = pos["quantity"]
                side = pos["side"]

                if side == "LONG":
                    unrealized_pnl = (current_price - entry_price) * quantity
                else:
                    unrealized_pnl = (entry_price - current_price) * quantity

                logger.debug(
                    "Position #%d: price=%.2f, unrealized_PnL=%.2f",
                    pos["id"],
                    current_price,
                    unrealized_pnl,
                )

    def get_open_positions(self) -> List[Dict[str, object]]:
        """Return all open positions."""
        return self._position_repo.get_open_positions()

    def get_position_summary(self) -> Dict[str, object]:
        """Get summary of all positions."""
        open_positions = self.get_open_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) or 0 for p in open_positions)

        return {
            "open_count": len(open_positions),
            "total_unrealized_pnl": total_unrealized,
            "positions": open_positions,
        }
