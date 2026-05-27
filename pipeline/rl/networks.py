"""
Dueling DDQN Network Architecture — Deep Q-Network with value/advantage decomposition.

Implements:
    - Standard DQN: Direct Q-value estimation
    - Double DQN: Decouples action selection from value estimation
    - Dueling DQN: Separates state value V(s) and advantage A(s,a) branches

Complies with FR-01: RL Core Architecture using Neural Network approximator
for high-dimensional State Space (OHLCV, Technical Indicators, etc.).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class DuelingDDQNNetwork(nn.Module):
    """Dueling Double Deep Q-Network architecture.

    Network structure:
        Input → Shared Feature Layers → Value Branch + Advantage Branch → Q-values

    The dueling decomposition:
        Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))

    This separation allows the network to learn the value of states
    independently of the advantages of each action, improving sample
    efficiency in states where all actions have similar values.

    Attributes:
        state_dim: Dimension of input state vector.
        action_dim: Number of discrete actions.
        hidden_dims: List of hidden layer sizes.
        dropout_rate: Dropout probability for regularization.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Tuple[int, ...] = (128, 128),
        dropout_rate: float = 0.0,
    ) -> None:
        """Initialize the Dueling DDQN network.

        Args:
            state_dim: Number of features in the input state.
            action_dim: Number of discrete actions (e.g., 3 for BUY/SELL/HOLD).
            hidden_dims: Tuple of hidden layer sizes for shared feature extractor.
            dropout_rate: Dropout rate for regularization (0.0 = disabled).
        """
        super().__init__()

        if state_dim <= 0:
            raise ValueError(f"state_dim must be positive, got {state_dim}")
        if action_dim <= 0:
            raise ValueError(f"action_dim must be positive, got {action_dim}")
        if not hidden_dims:
            raise ValueError("hidden_dims must not be empty")
        if not 0.0 <= dropout_rate < 1.0:
            raise ValueError(f"dropout_rate must be in [0, 1), got {dropout_rate}")

        self.state_dim = state_dim
        self.action_dim = action_dim

        # ── Shared Feature Extractor ──────────────────────────────
        layers: List[nn.Module] = []
        input_size = state_dim
        for hidden_size in hidden_dims:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.LayerNorm(hidden_size))
            layers.append(nn.ReLU())
            if dropout_rate > 0:
                layers.append(nn.Dropout(dropout_rate))
            input_size = hidden_size

        self.shared_features = nn.Sequential(*layers)
        shared_output_dim = hidden_dims[-1]

        # ── Value Branch: V(s) ────────────────────────────────────
        self.value_stream = nn.Sequential(
            nn.Linear(shared_output_dim, shared_output_dim // 2),
            nn.LayerNorm(shared_output_dim // 2),
            nn.ReLU(),
            nn.Linear(shared_output_dim // 2, 1),
        )

        # ── Advantage Branch: A(s,a) ──────────────────────────────
        self.advantage_stream = nn.Sequential(
            nn.Linear(shared_output_dim, shared_output_dim // 2),
            nn.LayerNorm(shared_output_dim // 2),
            nn.ReLU(),
            nn.Linear(shared_output_dim // 2, action_dim),
        )

        self._init_weights()

    def _init_weights(self) -> None:
        """Initialize weights using Kaiming uniform initialization."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Compute Q-values for all actions given a state.

        Args:
            state: Input state tensor of shape (batch_size, state_dim).

        Returns:
            Q-value tensor of shape (batch_size, action_dim).
        """
        features = self.shared_features(state)
        value = self.value_stream(features)  # (batch, 1)
        advantage = self.advantage_stream(features)  # (batch, action_dim)

        # Dueling combination: Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))
        q_values = value + (advantage - advantage.mean(dim=1, keepdim=True))
        return q_values

    def get_q_values(
        self, state: np.ndarray
    ) -> Tuple[np.ndarray, torch.Tensor]:
        """Get Q-values for a numpy state input.

        Args:
            state: State array of shape (state_dim,) or (batch, state_dim).

        Returns:
            Tuple of (numpy_q_values, torch_q_values).
        """
        was_1d = state.ndim == 1
        if was_1d:
            state = np.expand_dims(state, axis=0)

        with torch.no_grad():
            tensor_state = torch.FloatTensor(state)
            q_values = self(tensor_state)

        if was_1d:
            return q_values.numpy()[0], q_values[0]
        return q_values.numpy(), q_values

    def save(self, path: str) -> None:
        """Save network state dict to file.

        Args:
            path: File path for saving the model.
        """
        torch.save(self.state_dict(), path)
        logger.info("Saved network weights to %s", path)

    def load(self, path: str) -> None:
        """Load network state dict from file.

        Args:
            path: File path to load the model from.
        """
        self.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        logger.info("Loaded network weights from %s", path)


class StandardDQNNetwork(nn.Module):
    """Standard Deep Q-Network without dueling decomposition.

    Simple feed-forward network mapping states directly to Q-values.
    Useful as a baseline for comparison with Dueling DDQN.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Tuple[int, ...] = (128, 128),
    ) -> None:
        super().__init__()
        layers: List[nn.Module] = []
        input_size = state_dim
        for hidden_size in hidden_dims:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.ReLU())
            input_size = hidden_size
        layers.append(nn.Linear(input_size, action_dim))
        self.network = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.network(state)
