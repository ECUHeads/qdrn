"""
DDQN Agent — Double Deep Q-Network agent with epsilon-greedy exploration.

Implements the complete DDQN training loop including:
    - Epsilon-greedy action selection with decay schedule
    - Target network soft/hard updates
    - Experience replay integration
    - TD-error computation for prioritized replay

Complies with FR-01: RL Core Architecture using Neural Network Q-value approximator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from pipeline.rl.networks import DuelingDDQNNetwork

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for DDQN agent hyperparameters."""

    # Exploration
    epsilon_start: float = 1.0
    epsilon_end: float = 0.01
    epsilon_decay: float = 0.995
    epsilon_min: float = 0.01

    # Learning
    learning_rate: float = 3e-4
    gamma: float = 0.99  # Discount factor
    batch_size: int = 64
    target_update_freq: int = 1000  # Steps between target network updates
    tau: float = 0.005  # Soft update coefficient

    # Replay buffer
    buffer_capacity: int = 100_000
    warmup_steps: int = 1_000  # Steps before starting training

    # Network architecture
    hidden_dims: Tuple[int, ...] = (128, 128)
    dropout_rate: float = 0.0

    # Training
    max_grad_norm: float = 1.0
    use_prioritized_replay: bool = False
    per_alpha: float = 0.6
    per_beta: float = 0.4


class DDQNAgent:
    """Double Deep Q-Network agent for trading decisions.

    Uses two networks (online and target) to decouple action selection
    from value estimation, reducing overestimation bias in Q-values.

    Action space:
        0 = HOLD (maintain current position)
        1 = BUY (open/increase long position)
        2 = SELL (close long / open short position)

    Attributes:
        config: Agent hyperparameters.
        state_dim: Input state dimension.
        action_dim: Number of discrete actions.
        online_network: Primary Q-network being trained.
        target_network: Stabilized target for bootstrapping.
        optimizer: PyTorch optimizer for gradient descent.
        epsilon: Current exploration rate.
        step_count: Total environment steps taken.
        train_step_count: Total training updates performed.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        config: Optional[AgentConfig] = None,
    ) -> None:
        """Initialize the DDQN agent.

        Args:
            state_dim: Dimension of the observation space.
            action_dim: Number of discrete actions available.
            config: Agent configuration (uses defaults if None).
        """
        self.config = config or AgentConfig()
        self.state_dim = state_dim
        self.action_dim = action_dim

        # ── Networks ──────────────────────────────────────────────
        self.online_network = DuelingDDQNNetwork(
            state_dim=state_dim,
            action_dim=action_dim,
            hidden_dims=self.config.hidden_dims,
            dropout_rate=self.config.dropout_rate,
        )
        self.target_network = DuelingDDQNNetwork(
            state_dim=state_dim,
            action_dim=action_dim,
            hidden_dims=self.config.hidden_dims,
            dropout_rate=self.config.dropout_rate,
        )
        self._hard_update_target()

        # ── Optimizer ─────────────────────────────────────────────
        self.optimizer = optim.Adam(
            self.online_network.parameters(), lr=self.config.learning_rate
        )

        # ── State ─────────────────────────────────────────────────
        self.epsilon: float = self.config.epsilon_start
        self.step_count: int = 0
        self.train_step_count: int = 0
        self._loss_history: List[float] = []

    def select_action(self, state: np.ndarray, deterministic: bool = False) -> int:
        """Select action using epsilon-greedy policy.

        Args:
            state: Current observation vector.
            deterministic: If True, always select greedy action (for evaluation).

        Returns:
            Action index (0=HOLD, 1=BUY, 2=SELL).
        """
        if not deterministic and np.random.random() < self.epsilon:
            action = np.random.randint(0, self.action_dim)
        else:
            with torch.no_grad():
                tensor_state = torch.FloatTensor(state).unsqueeze(0)
                q_values = self.online_network(tensor_state)
                action = int(q_values.argmax(dim=1).item())
        return action

    def store_transition(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        replay_buffer,
    ) -> None:
        """Store a transition in the replay buffer.

        Args:
            state: Observation at time t.
            action: Action taken at time t.
            reward: Reward received.
            next_state: Observation at time t+1.
            done: Whether episode terminated.
            replay_buffer: ExperienceReplayBuffer instance.
        """
        replay_buffer.push(state, action, reward, next_state, done)

    def train(self, replay_buffer) -> Optional[float]:
        """Perform one training step by sampling from replay buffer.

        Uses Double DQN target computation:
            y = r + γ * Q_target(s', argmax_a Q_online(s', a))

        Args:
            replay_buffer: ExperienceReplayBuffer with stored transitions.

        Returns:
            TD loss value, or None if not enough data for training.
        """
        if replay_buffer.size < max(self.config.warmup_steps, self.config.batch_size):
            return None

        # Sample batch
        if self.config.use_prioritized_replay:
            batch, indices, is_weights = replay_buffer.sample(self.config.batch_size)
        else:
            batch = replay_buffer.sample(self.config.batch_size)
            indices = None
            is_weights = None

        # Convert to tensors
        states = torch.FloatTensor(batch["states"])
        actions = torch.LongTensor(batch["actions"]).unsqueeze(1)
        rewards = torch.FloatTensor(batch["rewards"]).unsqueeze(1)
        next_states = torch.FloatTensor(batch["next_states"])
        dones = torch.FloatTensor(batch["dones"]).unsqueeze(1)

        # ── Double DQN Target Computation ─────────────────────────
        # Online network selects best action for next state
        with torch.no_grad():
            online_next_q = self.online_network(next_states)
            best_actions = online_next_q.argmax(dim=1, keepdim=True)

            # Target network evaluates that action
            target_next_q = self.target_network(next_states)
            gathered_target_q = target_next_q.gather(1, best_actions)

            # Bellman target: r + γ * Q_target(s', a*) * (1 - done)
            targets = rewards + (self.config.gamma * gathered_target_q * (1.0 - dones))

        # Current Q-values for taken actions
        current_q_values = self.online_network(states).gather(1, actions)

        # TD loss with huber loss for stability
        td_errors = torch.abs(targets - current_q_values).detach().clone()
        loss = nn.SmoothL1Loss()(current_q_values, targets)

        if is_weights is not None:
            is_weight_tensor = torch.FloatTensor(is_weights).unsqueeze(1)
            loss = (loss * is_weight_tensor).mean()

        # ── Backpropagation ───────────────────────────────────────
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(
            self.online_network.parameters(), self.config.max_grad_norm
        )
        self.optimizer.step()

        # ── Update Priorities (PER) ───────────────────────────────
        if self.config.use_prioritized_replay and indices is not None:
            priorities = td_errors.squeeze().numpy()
            replay_buffer.update_priorities(indices, priorities)

        # ── Target Network Update ─────────────────────────────────
        self.train_step_count += 1
        if self.train_step_count % self.config.target_update_freq == 0:
            self._soft_update_target()

        # Track loss
        loss_value = loss.item()
        self._loss_history.append(loss_value)
        return loss_value

    def decay_epsilon(self) -> None:
        """Decay exploration rate according to schedule."""
        self.epsilon = max(
            self.config.epsilon_min,
            self.epsilon * self.config.epsilon_decay,
        )

    def _soft_update_target(self) -> None:
        """Soft update target network: θ' ← τθ + (1-τ)θ'."""
        for target_param, online_param in zip(
            self.target_network.parameters(),
            self.online_network.parameters(),
        ):
            target_param.data.copy_(
                self.config.tau * online_param.data
                + (1.0 - self.config.tau) * target_param.data
            )

    def _hard_update_target(self) -> None:
        """Hard copy online network weights to target network."""
        self.target_network.load_state_dict(self.online_network.state_dict())

    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get current Q-value estimates for all actions.

        Args:
            state: Current observation vector.

        Returns:
            Array of Q-values for each action.
        """
        q_vals, _ = self.online_network.get_q_values(state)
        return q_vals

    def save(self, path: str) -> None:
        """Save agent state (networks, optimizer, epsilon).

        Args:
            path: Directory path for saving checkpoint files.
        """
        import os
        os.makedirs(path, exist_ok=True)
        self.online_network.save(f"{path}/online_net.pth")
        self.target_network.save(f"{path}/target_net.pth")
        torch.save(
            {
                "optimizer": self.optimizer.state_dict(),
                "epsilon": self.epsilon,
                "step_count": self.step_count,
                "train_step_count": self.train_step_count,
            },
            f"{path}/agent_state.pth",
        )
        logger.info("Saved agent checkpoint to %s", path)

    def load(self, path: str) -> None:
        """Load agent state from checkpoint.

        Args:
            path: Directory path containing checkpoint files.
        """
        self.online_network.load(f"{path}/online_net.pth")
        self.target_network.load(f"{path}/target_net.pth")
        state = torch.load(f"{path}/agent_state.pth", map_location="cpu", weights_only=True)
        self.optimizer.load_state_dict(state["optimizer"])
        self.epsilon = state["epsilon"]
        self.step_count = state["step_count"]
        self.train_step_count = state["train_step_count"]
        logger.info("Loaded agent checkpoint from %s", path)

    @property
    def loss_history(self) -> List[float]:
        """History of training losses."""
        return self._loss_history
