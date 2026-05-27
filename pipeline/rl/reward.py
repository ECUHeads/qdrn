"""
Reward Function Engineering — Computes trading rewards for RL training.

Implements reward shaping combining:
    - Net P&L (after commission and slippage)
    - Drawdown penalty when max drawdown exceeds threshold
    - Position holding cost to discourage idle positions
    - Sharpe ratio bonus for risk-adjusted returns

Complies with FR-04: Action & Reward Engineering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RewardConfig:
    """Configuration parameters for reward computation."""

    # Commission rate (e.g., 0.001 = 0.1%)
    commission_rate: float = 0.001

    # Slippage rate (e.g., 0.0005 = 0.05%)
    slippage_rate: float = 0.0005

    # Max drawdown threshold for penalty trigger
    max_drawdown_threshold: float = 0.15

    # Drawdown penalty multiplier
    drawdown_penalty_multiplier: float = 2.0

    # Position holding cost per step (discourages idle positions)
    holding_cost: float = 0.0

    # Sharpe ratio annualization factor (for daily data: sqrt(252))
    sharpe_annualization: float = np.sqrt(252)

    # Risk-free rate (annualized)
    risk_free_rate: float = 0.04


class RewardFunction:
    """Compute shaped rewards for trading environment steps.

    Combines multiple reward signals into a single scalar reward
    that guides the agent toward profitable, low-risk trading policies.

    Attributes:
        config: Reward configuration parameters.
        peak_equity: Track peak equity for drawdown calculation.
        returns_history: Rolling window of step returns for Sharpe calc.
    """

    def __init__(self, config: Optional[RewardConfig] = None) -> None:
        self.config = config or RewardConfig()
        self.peak_equity: float = 0.0
        self.returns_history: List[float] = []

    def reset(self, initial_equity: float) -> None:
        """Reset reward state for a new episode.

        Args:
            initial_equity: Starting portfolio equity.
        """
        self.peak_equity = initial_equity
        self.returns_history = []

    def compute(
        self,
        prev_equity: float,
        current_equity: float,
        action: int,
        position_size: float,
        price_change: float = 0.0,
        *,
        is_terminal: bool = False,
    ) -> Tuple[float, Dict[str, float]]:
        """Compute the shaped reward for a single environment step.

        Args:
            prev_equity: Portfolio equity before the action.
            current_equity: Portfolio equity after the action.
            action: Action taken (0=HOLD, 1=BUY, 2=SELL).
            position_size: Current position size as fraction of equity.
            price_change: Relative price change during this step.
            is_terminal: Whether this is the final step of the episode.

        Returns:
            Tuple of (reward_scalar, reward_breakdown_dict).
        """
        if prev_equity <= 0:
            return -1.0, {"error": "Invalid equity"}

        # ── 1. P&L Component ──────────────────────────────────────
        pnl = current_equity - prev_equity
        pnl_return = pnl / prev_equity

        # ── 2. Transaction Cost Penalty ───────────────────────────
        transaction_cost = 0.0
        if action in (1, 2):  # BUY or SELL
            trade_value = prev_equity * position_size
            transaction_cost = trade_value * (
                self.config.commission_rate + self.config.slippage_rate
            )

        # ── 3. Drawdown Penalty ───────────────────────────────────
        drawdown_penalty = 0.0
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        current_drawdown = 0.0
        if self.peak_equity > 0:
            current_drawdown = (self.peak_equity - current_equity) / self.peak_equity

        if current_drawdown > self.config.max_drawdown_threshold:
            excess_dd = current_drawdown - self.config.max_drawdown_threshold
            drawdown_penalty = -self.config.drawdown_penalty_multiplier * excess_dd

        # ── 4. Holding Cost ───────────────────────────────────────
        holding_penalty = 0.0
        if self.config.holding_cost > 0 and position_size > 0:
            holding_penalty = -self.config.holding_cost * position_size

        # ── 5. Sharpe Ratio Bonus (rolling) ───────────────────────
        sharpe_bonus = 0.0
        self.returns_history.append(pnl_return)
        if len(self.returns_history) >= 20:
            recent_returns = np.array(self.returns_history[-60:])
            mean_ret = np.mean(recent_returns)
            std_ret = np.std(recent_returns)
            if std_ret > 1e-8:
                sharpe = (
                    (mean_ret / std_ret) * self.config.sharpe_annualization
                )
                sharpe_bonus = sharpe * 0.1  # Scale down to avoid dominating

        # ── 6. Terminal Bonus/Penalty ─────────────────────────────
        terminal_bonus = 0.0
        if is_terminal:
            total_return = (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            # Final Sharpe bonus at episode end
            if len(self.returns_history) >= 20:
                all_returns = np.array(self.returns_history)
                mean_ret = np.mean(all_returns)
                std_ret = np.std(all_returns)
                if std_ret > 1e-8:
                    terminal_sharpe = (mean_ret / std_ret) * self.config.sharpe_annualization
                    terminal_bonus = terminal_sharpe * 0.5

        # ── Combine ───────────────────────────────────────────────
        reward = (
            pnl_return
            - transaction_cost / prev_equity
            + drawdown_penalty
            + holding_penalty
            + sharpe_bonus
            + terminal_bonus
        )

        breakdown: Dict[str, float] = {
            "pnl_return": round(float(pnl_return), 8),
            "transaction_cost": round(float(transaction_cost / prev_equity), 8),
            "drawdown_penalty": round(float(drawdown_penalty), 8),
            "holding_penalty": round(float(holding_penalty), 8),
            "sharpe_bonus": round(float(sharpe_bonus), 8),
            "terminal_bonus": round(float(terminal_bonus), 8),
            "current_drawdown": round(float(current_drawdown), 6),
            "peak_equity": round(float(self.peak_equity), 2),
        }

        return float(reward), breakdown

    def compute_simple(
        self,
        prev_price: float,
        current_price: float,
        action: int,
        position: int,
    ) -> float:
        """Compute simplified reward based on price movement and position.

        Useful for baseline training before adding complex shaping.

        Args:
            prev_price: Asset price at previous step.
            current_price: Asset price at current step.
            action: Action taken (0=HOLD, 1=BUY, 2=SELL).
            position: Current position (-1=short, 0=flat, 1=long).

        Returns:
            Scalar reward value.
        """
        if prev_price <= 0:
            return 0.0

        price_return = (current_price - prev_price) / prev_price

        # Reward is position-aligned with price movement
        reward = position * price_return

        # Transaction cost on trade actions
        if action in (1, 2):  # BUY or SELL
            reward -= self.config.commission_rate + self.config.slippage_rate

        return float(reward)
