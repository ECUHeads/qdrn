"""
Training Pipeline — Walk-forward validation loop for DRL agent training.

Implements:
    - Walk-forward validation with configurable train/validation splits
    - Episode-based training with early stopping
    - Performance metrics tracking (Sharpe, Drawdown, Returns)
    - Model checkpointing and experiment logging

Complies with FR-05: Validation & Backtesting Pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pipeline.rl.agent import AgentConfig, DDQNAgent
from pipeline.rl.environment import EnvironmentConfig, TradingEnvironment
from pipeline.rl.replay_buffer import (
    ExperienceReplayBuffer,
    PrioritizedReplayBuffer,
)

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for the training pipeline."""

    # Training
    n_episodes: int = 100
    max_steps_per_episode: int = 10_000
    eval_interval: int = 10  # Evaluate every N episodes
    checkpoint_interval: int = 50  # Save checkpoint every N episodes

    # Walk-forward validation
    train_ratio: float = 0.8
    val_ratio: float = 0.2

    # Early stopping
    early_stopping_patience: int = 20
    early_stopping_min_delta: float = 1e-4

    # Checkpointing
    checkpoint_dir: str = "checkpoints"
    save_best_only: bool = True

    # Agent config override (None = use defaults)
    agent_config: Optional[AgentConfig] = None

    # Environment config override
    env_config: Optional[EnvironmentConfig] = None


@dataclass
class TrainingMetrics:
    """Container for training metrics and statistics."""

    episode_rewards: List[float] = field(default_factory=list)
    episode_lengths: List[int] = field(default_factory=list)
    episode_sharpe: List[float] = field(default_factory=list)
    episode_drawdowns: List[float] = field(default_factory=list)
    episode_returns: List[float] = field(default_factory=list)
    training_losses: List[float] = field(default_factory=list)
    eval_metrics: List[Dict[str, float]] = field(default_factory=list)
    best_sharpe: float = float("-inf")
    best_epoch: int = 0
    total_training_time: float = 0.0


class TrainingPipeline:
    """Walk-forward training pipeline for DRL trading agent.

    Manages the complete training loop including:
        - Data splitting (train/validation)
        - Episode-based training with experience replay
        - Periodic evaluation on validation data
        - Model checkpointing based on Sharpe ratio
        - Early stopping when performance plateaus

    Attributes:
        config: Training configuration.
        agent: DDQN agent being trained.
        replay_buffer: Experience replay storage.
        metrics: Collected training metrics.
    """

    def __init__(
        self,
        data: np.ndarray,
        config: Optional[TrainingConfig] = None,
    ) -> None:
        """Initialize the training pipeline.

        Args:
            data: Full dataset array of shape (n_timesteps, n_features).
            config: Training configuration parameters.
        """
        self.config = config or TrainingConfig()
        self.full_data = data
        self.metrics = TrainingMetrics()

        # Split data into train/validation
        n_samples = len(data)
        train_end = int(n_samples * self.config.train_ratio)
        self.train_data = data[:train_end]
        self.val_data = data[train_end:]

        # Determine state and action dimensions
        n_features_window = self.config.env_config.state_window * data.shape[1] if self.config.env_config else 20 * data.shape[1]
        action_dim = 3  # HOLD, BUY, SELL

        # Initialize agent
        agent_cfg = self.config.agent_config or AgentConfig()
        self.agent = DDQNAgent(
            state_dim=n_features_window,
            action_dim=action_dim,
            config=agent_cfg,
        )

        # Initialize replay buffer
        if agent_cfg.use_prioritized_replay:
            self.replay_buffer = PrioritizedReplayBuffer(
                capacity=agent_cfg.buffer_capacity,
                alpha=agent_cfg.per_alpha,
                beta=agent_cfg.per_beta,
            )
        else:
            self.replay_buffer = ExperienceReplayBuffer(
                capacity=agent_cfg.buffer_capacity
            )

        # Environment configs
        self.env_config = self.config.env_config or EnvironmentConfig()
        self.eval_env_config = self.config.env_config or EnvironmentConfig()
        self.eval_env_config.max_steps = min(
            self.config.max_steps_per_episode, len(self.val_data) - self.env_config.state_window
        )

        # Early stopping state
        self._patience_counter: int = 0

        logger.info(
            "Training pipeline initialized: train=%d, val=%d samples",
            len(self.train_data),
            len(self.val_data),
        )

    def train(self) -> TrainingMetrics:
        """Execute the full training loop.

        Returns:
            TrainingMetrics with complete training history.
        """
        start_time = time.monotonic()
        logger.info("Starting training for %d episodes", self.config.n_episodes)

        for episode in range(1, self.config.n_episodes + 1):
            # ── Train Episode ─────────────────────────────────────
            episode_reward, episode_length = self._run_training_episode()
            self.metrics.episode_rewards.append(episode_reward)
            self.metrics.episode_lengths.append(episode_length)

            # Decay exploration rate
            self.agent.decay_epsilon()
            self.agent.step_count += episode_length

            # ── Log Progress ──────────────────────────────────────
            if episode % 10 == 0:
                avg_reward = np.mean(self.metrics.episode_rewards[-10:])
                logger.info(
                    "Episode %d | Reward: %.4f (avg10: %.4f) | "
                    "Epsilon: %.4f | Buffer: %d | Loss: %.6f",
                    episode,
                    episode_reward,
                    avg_reward,
                    self.agent.epsilon,
                    self.replay_buffer.size,
                    self.metrics.training_losses[-1] if self.metrics.training_losses else 0.0,
                )

            # ── Evaluation ────────────────────────────────────────
            if episode % self.config.eval_interval == 0:
                eval_result = self._evaluate()
                self.metrics.eval_metrics.append(eval_result)

                sharpe = eval_result.get("sharpe_ratio", 0.0)
                logger.info(
                    "Eval @ Episode %d | Sharpe: %.4f | Return: %.4f | "
                    "Drawdown: %.4f",
                    episode,
                    sharpe,
                    eval_result.get("total_return", 0.0),
                    eval_result.get("max_drawdown", 0.0),
                )

                # Track best model
                if sharpe > self.metrics.best_sharpe + self.config.early_stopping_min_delta:
                    self.metrics.best_sharpe = sharpe
                    self.metrics.best_epoch = episode
                    self._patience_counter = 0

                    if not self.config.save_best_only or True:
                        self._save_checkpoint(episode, sharpe)
                else:
                    self._patience_counter += 1

            # ── Checkpoint ────────────────────────────────────────
            if (
                episode % self.config.checkpoint_interval == 0
                and not self.config.save_best_only
            ):
                self._save_checkpoint(episode)

            # ── Early Stopping ────────────────────────────────────
            if self._patience_counter >= self.config.early_stopping_patience:
                logger.info(
                    "Early stopping at episode %d (patience=%d, best_sharpe=%.4f)",
                    episode,
                    self.config.early_stopping_patience,
                    self.metrics.best_sharpe,
                )
                break

        self.metrics.total_training_time = time.monotonic() - start_time
        logger.info(
            "Training completed in %.1fs | Best Sharpe: %.4f @ Episode %d",
            self.metrics.total_training_time,
            self.metrics.best_sharpe,
            self.metrics.best_epoch,
        )

        return self.metrics

    def _run_training_episode(self) -> Tuple[float, int]:
        """Run a single training episode on training data.

        Returns:
            Tuple of (total_reward, episode_length).
        """
        env = TradingEnvironment(self.train_data, self.env_config)
        obs, _ = env.reset()
        total_reward = 0.0
        step_count = 0

        while True:
            action = self.agent.select_action(obs)
            next_obs, reward, terminated, truncated, info = env.step(action)

            # Store transition
            self.agent.store_transition(
                state=obs,
                action=action,
                reward=reward,
                next_state=next_obs,
                done=terminated,
                replay_buffer=self.replay_buffer,
            )

            # Train agent
            loss = self.agent.train(self.replay_buffer)
            if loss is not None:
                self.metrics.training_losses.append(loss)

            total_reward += reward
            obs = next_obs
            step_count += 1

            if terminated or truncated:
                break

        # Collect episode stats
        stats = env.get_episode_stats()
        self.metrics.episode_sharpe.append(stats["sharpe_ratio"])
        self.metrics.episode_drawdowns.append(stats["max_drawdown"])
        self.metrics.episode_returns.append(stats["total_return"])

        return total_reward, step_count

    def _evaluate(self) -> Dict[str, float]:
        """Evaluate agent on validation data (deterministic policy).

        Returns:
            Dictionary with evaluation metrics.
        """
        if len(self.val_data) < self.env_config.state_window + 1:
            return {"total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0}

        env = TradingEnvironment(self.val_data, self.eval_env_config)
        obs, _ = env.reset()
        total_reward = 0.0

        while True:
            # Deterministic action selection (greedy)
            action = self.agent.select_action(obs, deterministic=True)
            next_obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            obs = next_obs

            if terminated or truncated:
                break

        stats = env.get_episode_stats()
        stats["total_reward"] = total_reward
        return stats

    def _save_checkpoint(self, episode: int, sharpe: float = 0.0) -> None:
        """Save model checkpoint.

        Args:
            episode: Current episode number.
            sharpe: Current Sharpe ratio (for filename).
        """
        checkpoint_path = Path(self.config.checkpoint_dir) / f"episode_{episode}"
        if sharpe > 0:
            checkpoint_path = Path(self.config.checkpoint_dir) / f"best_sharpe_{sharpe:.4f}_ep{episode}"

        try:
            self.agent.save(str(checkpoint_path))
            logger.info("Saved checkpoint: %s", checkpoint_path)
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)

    def predict(
        self, data: np.ndarray, start_index: Optional[int] = None
    ) -> List[int]:
        """Generate trading signals using the trained agent.

        Args:
            data: Input data array (n_timesteps, n_features).
            start_index: Optional starting index for prediction window.

        Returns:
            List of action predictions (0=HOLD, 1=BUY, 2=SELL).
        """
        env = TradingEnvironment(data, self.env_config)
        obs, _ = env.reset(options={"start_index": start_index or 0})
        predictions: List[int] = []

        while True:
            action = self.agent.select_action(obs, deterministic=True)
            predictions.append(action)
            next_obs, _, terminated, truncated, _ = env.step(action)
            obs = next_obs
            if terminated or truncated:
                break

        return predictions
