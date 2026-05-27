"""
Trading Environment — Gym-compatible environment for RL-based trading.

Implements OpenAI Gymnasium interface with:
    - State Space: OHLCV + Technical Indicators (RSI, MACD, BB, ATR)
    - Action Space: Discrete {0=HOLD, 1=BUY, 2=SELL}
    - Reward: Configurable via RewardFunction (P&L, costs, drawdown penalty)
    - Transaction Costs: Commission + Slippage simulation
    - Position Tracking: Long/Short/Flat with position sizing

Complies with FR-02 (Trading Environment), FR-03 (State Space Design),
and FR-04 (Action & Reward Engineering).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium.spaces import Box, Discrete

from pipeline.rl.reward import RewardConfig, RewardFunction

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentConfig:
    """Configuration for TradingEnvironment."""

    # Initial portfolio equity
    initial_equity: float = 10_000.0

    # Position sizing (fraction of equity per trade)
    position_size: float = 0.95

    # Commission rate
    commission_rate: float = 0.001

    # Slippage rate
    slippage_rate: float = 0.0005

    # State window size (number of timesteps in observation)
    state_window: int = 20

    # Feature columns to include in state vector
    feature_columns: List[str] = field(
        default_factory=lambda: [
            "Open", "High", "Low", "Close", "Volume",
            "rsi_14", "macd_12_26", "macd_signal",
            "bb_upper", "bb_lower", "atr_14",
        ]
    )

    # Reward configuration
    reward_config: Optional[RewardConfig] = None

    # Max episodes steps before forced termination
    max_steps: int = 10_000


class TradingEnvironment(gym.Env):
    """Gymnasium-compatible trading environment.

    Observation Space:
        Box(low=-inf, high=inf, shape=(state_window * n_features,))
        Flattened matrix of [window_size, feature_count] containing
        normalized OHLCV data and technical indicators.

    Action Space:
        Discrete(3) — {0: HOLD, 1: BUY, 2: SELL}

    Attributes:
        config: Environment configuration.
        data: Full dataset (numpy array of feature values).
        reward_fn: Reward computation function.
        current_step: Current timestep index.
        equity: Current portfolio equity.
        position: Current position (-1=short, 0=flat, 1=long).
        entry_price: Price at which current position was opened.
        peak_equity: Peak equity for drawdown tracking.
    """

    metadata = {"render_modes": ["human"], "render_mode": None}

    def __init__(
        self,
        data: np.ndarray,
        config: Optional[EnvironmentConfig] = None,
        render_mode: Optional[str] = None,
    ) -> None:
        """Initialize the trading environment.

        Args:
            data: 2D array of shape (n_timesteps, n_features) containing
                OHLCV and technical indicator columns.
            config: Environment configuration parameters.
            render_mode: Optional render mode ("human").
        """
        super().__init__()

        self.config = config or EnvironmentConfig()
        self.render_mode = render_mode
        self.data = data.copy()

        if self.data.ndim != 2:
            raise ValueError(f"Data must be 2D, got shape {self.data.shape}")
        if self.data.shape[0] < self.config.state_window + 1:
            raise ValueError(
                f"Data rows ({self.data.shape[0]}) must exceed "
                f"state_window ({self.config.state_window}) + 1"
            )

        n_features = self.data.shape[1]
        obs_shape = self.config.state_window * n_features

        # Observation space: flattened window of features
        self.observation_space = Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_shape,),
            dtype=np.float64,
        )

        # Action space: 0=HOLD, 1=BUY, 2=SELL
        self.action_space = Discrete(3)

        # ── Reward Function ───────────────────────────────────────
        self.reward_fn = RewardFunction(self.config.reward_config)

        # ── Runtime State (reset each episode) ────────────────────
        self.current_step: int = 0
        self.equity: float = 0.0
        self.position: int = 0  # -1, 0, 1
        self.entry_price: float = 0.0
        self.peak_equity: float = 0.0
        self._episode_returns: List[float] = []
        self._done: bool = False

    def reset(
        self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset environment to initial state.

        Args:
            seed: Random seed for reproducibility.
            options: Optional dict with 'start_index' key to begin
                episode at a specific timestep.

        Returns:
            Tuple of (observation, info).
        """
        super().reset(seed=seed)

        start_index = 0
        if options and "start_index" in options:
            start_index = options["start_index"]

        self.current_step = start_index + self.config.state_window - 1
        self.equity = self.config.initial_equity
        self.position = 0
        self.entry_price = 0.0
        self.peak_equity = self.config.initial_equity
        self._episode_returns = []
        self._done = False

        self.reward_fn.reset(self.config.initial_equity)

        obs = self._get_observation()
        info = self._get_info()
        return obs, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """Execute one environment step.

        Args:
            action: Action index (0=HOLD, 1=BUY, 2=SELL).

        Returns:
            Tuple of (observation, reward, terminated, truncated, info).
        """
        if self._done:
            raise RuntimeError("Environment already terminated. Call reset().")

        prev_equity = self.equity
        current_price = self._get_close_price(self.current_step)
        prev_price = self._get_close_price(self.current_step - 1) if self.current_step > 0 else current_price

        # ── Execute Action ────────────────────────────────────────
        transaction_cost = self._execute_action(action, current_price)

        # ── Update Equity ─────────────────────────────────────────
        unrealized_pnl = self._calculate_unrealized_pnl(current_price)
        self.equity = self.equity + unrealized_pnl - transaction_cost

        # ── Compute Reward ────────────────────────────────────────
        price_change = (current_price - prev_price) / prev_price if prev_price > 0 else 0.0
        reward, reward_breakdown = self.reward_fn.compute(
            prev_equity=prev_equity,
            current_equity=self.equity,
            action=action,
            position_size=self.config.position_size if self.position != 0 else 0.0,
            price_change=price_change,
        )

        # Track returns
        step_return = (self.equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        self._episode_returns.append(step_return)

        # ── Advance Step ──────────────────────────────────────────
        self.current_step += 1

        # ── Check Termination ─────────────────────────────────────
        terminated = self.current_step >= len(self.data)
        truncated = len(self._episode_returns) >= self.config.max_steps

        if terminated:
            self._done = True

        obs = self._get_observation()
        info = self._get_info()
        info["reward_breakdown"] = reward_breakdown
        info["transaction_cost"] = transaction_cost
        info["current_price"] = current_price

        return obs, float(reward), terminated, truncated, info

    def render(self) -> None:
        """Render current environment state (for debugging)."""
        if self.render_mode != "human":
            return
        print(
            f"Step: {self.current_step} | "
            f"Equity: {self.equity:.2f} | "
            f"Position: {self.position} | "
            f"Price: {self._get_close_price(self.current_step):.2f}"
        )

    # ── Private Methods ───────────────────────────────────────────

    def _get_observation(self) -> np.ndarray:
        """Extract current state window as flattened observation."""
        start = self.current_step - self.config.state_window + 1
        if start < 0:
            # Pad with first available data
            window = np.tile(self.data[0], (self.config.state_window, 1))
            window[max(0, -start):] = self.data[:self.current_step + 1]
        else:
            window = self.data[start : self.current_step + 1]

        # NaN safety: replace with zeros
        window = np.nan_to_num(window, nan=0.0, posinf=0.0, neginf=0.0)
        return window.flatten()

    def _get_close_price(self, idx: int) -> float:
        """Get close price at given index (column 3 = Close in OHLCV)."""
        if idx < 0 or idx >= len(self.data):
            return self.data[0, 3]  # Fallback to first close
        return float(self.data[idx, 3])

    def _execute_action(
        self, action: int, current_price: float
    ) -> float:
        """Execute trading action and return transaction cost.

        Args:
            action: Action index (0=HOLD, 1=BUY, 2=SELL).
            current_price: Current market price.

        Returns:
            Transaction cost incurred.
        """
        if action == 0:  # HOLD
            return 0.0

        trade_value = self.equity * self.config.position_size
        commission = trade_value * self.config.commission_rate
        slippage = trade_value * self.config.slippage_rate

        if action == 1:  # BUY
            if self.position == 0:
                self.position = 1
                self.entry_price = current_price
            return commission + slippage

        if action == 2:  # SELL
            if self.position == 1:
                # Close long position
                self.position = 0
                self.entry_price = 0.0
            elif self.position == 0:
                # Open short position
                self.position = -1
                self.entry_price = current_price
            return commission + slippage

        return 0.0

    def _calculate_unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L for current position."""
        if self.position == 0 or self.entry_price == 0:
            return 0.0

        shares = (self.equity * self.config.position_size) / self.entry_price
        if self.position == 1:  # Long
            return (current_price - self.entry_price) * shares
        else:  # Short
            return (self.entry_price - current_price) * shares

    def _get_info(self) -> Dict[str, Any]:
        """Build info dictionary with episode statistics."""
        total_return = (self.equity - self.config.initial_equity) / self.config.initial_equity
        peak = max(self.peak_equity, self.equity)
        drawdown = (peak - self.equity) / peak if peak > 0 else 0.0

        return {
            "equity": self.equity,
            "position": self.position,
            "total_return": total_return,
            "drawdown": drawdown,
            "step": self.current_step,
            "episode_returns": list(self._episode_returns),
        }

    def get_episode_stats(self) -> Dict[str, float]:
        """Calculate episode-level performance statistics."""
        if not self._episode_returns:
            return {"total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0}

        returns = np.array(self._episode_returns)
        total_return = (self.equity - self.config.initial_equity) / self.config.initial_equity

        # Calculate cumulative equity curve for drawdown
        cumulative = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (peak - cumulative) / np.where(peak > 0, peak, 1)
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # Sharpe ratio (annualized for daily data)
        sharpe = 0.0
        if len(returns) >= 2 and np.std(returns) > 1e-8:
            sharpe = float(
                (np.mean(returns) / np.std(returns)) * np.sqrt(252)
            )

        return {
            "total_return": float(total_return),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 6),
            "n_steps": len(self._episode_returns),
            "final_equity": self.equity,
        }
