"""
Experience Replay Buffer — Stores and samples transition tuples for DQN training.

Implements a fixed-size circular buffer with uniform sampling and optional
prioritized experience replay (PER) support using sum-tree structure.

Reduces correlation between consecutive samples and improves sample efficiency.
"""

from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Single transition tuple (state, action, reward, next_state, done)."""

    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class ExperienceReplayBuffer:
    """Fixed-size experience replay buffer with uniform sampling.

    Stores (state, action, reward, next_state, done) tuples and samples
    random batches for DQN training. Uses a deque for O(1) append/popleft.

    Attributes:
        capacity: Maximum number of experiences to store.
        buffer: Internal deque storing Experience objects.
        _count: Total number of experiences added (for monitoring).
    """

    def __init__(self, capacity: int = 100_000) -> None:
        """Initialize the replay buffer.

        Args:
            capacity: Maximum buffer size. Older experiences are evicted
                when the buffer reaches capacity.
        """
        if capacity <= 0:
            raise ValueError(f"Capacity must be positive, got {capacity}")
        self.capacity = capacity
        self.buffer: deque[Experience] = deque(maxlen=capacity)
        self._count: int = 0

    @property
    def count(self) -> int:
        """Total experiences added to the buffer."""
        return self._count

    @property
    def size(self) -> int:
        """Current number of experiences in the buffer."""
        return len(self.buffer)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Add a single transition to the buffer.

        Args:
            state: Observation at time t.
            action: Action taken at time t.
            reward: Reward received after taking action.
            next_state: Observation at time t+1.
            done: Whether the episode terminated after this transition.
        """
        experience = Experience(
            state=state.copy(),
            action=action,
            reward=float(reward),
            next_state=next_state.copy(),
            done=bool(done),
        )
        self.buffer.append(experience)
        self._count += 1

    def sample(
        self, batch_size: int, weights: Optional[np.ndarray] = None
    ) -> Dict[str, np.ndarray]:
        """Sample a random batch of experiences.

        Args:
            batch_size: Number of transitions to sample.
            weights: Optional sampling weights (for PER). Ignored in
                uniform sampling mode.

        Returns:
            Dictionary with keys: states, actions, rewards, next_states, dones.

        Raises:
            ValueError: If batch_size exceeds current buffer size.
        """
        if batch_size > self.size:
            raise ValueError(
                f"Batch size {batch_size} exceeds buffer size {self.size}"
            )
        if batch_size <= 0:
            raise ValueError(f"Batch size must be positive, got {batch_size}")

        samples = random.sample(list(self.buffer), batch_size)

        return {
            "states": np.array([s.state for s in samples]),
            "actions": np.array([s.action for s in samples]),
            "rewards": np.array([s.reward for s in samples]),
            "next_states": np.array([s.next_state for s in samples]),
            "dones": np.array([s.done for s in samples]),
        }

    def clear(self) -> None:
        """Empty the buffer."""
        self.buffer.clear()


class PrioritizedReplayBuffer(ExperienceReplayBuffer):
    """Prioritized Experience Replay (PER) using sum-tree structure.

    Samples transitions proportional to their priority (TD error magnitude),
    allowing the network to focus on important/surprising experiences.

    Attributes:
        alpha: Priority exponent (0=uniform, 1=pure PER).
        beta: Importance sampling weight annealing rate.
        beta_frames: Number of frames to anneal beta to 1.0.
        _priorities: Array storing priority values for sum-tree.
        _tree_size: Size of the underlying sum-tree array.
    """

    def __init__(
        self,
        capacity: int = 100_000,
        alpha: float = 0.6,
        beta: float = 0.4,
        beta_frames: int = 100_000,
    ) -> None:
        """Initialize the prioritized replay buffer.

        Args:
            capacity: Maximum buffer size.
            alpha: Priority exponent (0.0 = uniform sampling, 1.0 = full PER).
            beta: Initial importance sampling weight. Anneals to 1.0 over
                beta_frames steps.
            beta_frames: Number of training steps to anneal beta.
        """
        super().__init__(capacity=capacity)
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"Alpha must be in [0, 1], got {alpha}")
        if not 0.0 <= beta <= 1.0:
            raise ValueError(f"Beta must be in [0, 1], got {beta}")

        self.alpha = alpha
        self.beta = beta
        self.beta_frames = beta_frames
        self._frame_idx: int = 0
        # Sum-tree backed by power-of-2 size array
        self._tree_size: int = 1
        while self._tree_size < capacity:
            self._tree_size *= 2
        self._tree: np.ndarray = np.zeros(2 * self._tree_size, dtype=np.float64)
        self._max_priority: float = 1.0

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Add transition with maximum priority for first-time sampling."""
        super().push(state, action, reward, next_state, done)
        tree_idx = self.size - 1
        self._update_tree_idx(tree_idx, self._max_priority)

    def _update_tree_idx(self, idx: int, priority: float) -> None:
        """Update priority value in the sum-tree.

        Args:
            idx: Index in the buffer (0 to capacity-1).
            priority: New priority value (must be > 0).
        """
        if priority <= 0:
            priority = 1e-8
        tree_idx = idx + self._tree_size
        delta = priority - self._tree[tree_idx]
        self._tree[tree_idx] = priority
        while tree_idx > 0:
            tree_idx = (tree_idx - 1) // 2
            self._tree[tree_idx] += delta

    def _retrieve(
        self, v: float, internal_node_idx: int
    ) -> Tuple[int, float, float]:
        """Walk down the sum-tree to find a leaf node.

        Args:
            v: Random value in [0, total_priority].
            internal_node_idx: Starting internal node index.

        Returns:
            Tuple of (buffer_index, priority, IS_weight).
        """
        while True:
            left = 2 * internal_node_idx + 1
            right = left + 1
            if left >= len(self._tree):
                leaf_idx = internal_node_idx - self._tree_size
                priority = self._tree[internal_node_idx]
                is_weight = (self.size * priority ** (-self.beta)) / (
                    self._max_priority ** (-self.beta)
                )
                return leaf_idx, float(priority), float(is_weight)
            if v <= self._tree[left]:
                internal_node_idx = left
            else:
                v -= self._tree[left]
                internal_node_idx = right

    def sample(
        self, batch_size: int
    ) -> Tuple[Dict[str, np.ndarray], np.ndarray, np.ndarray]:
        """Sample a prioritized batch with importance sampling weights.

        Args:
            batch_size: Number of transitions to sample.

        Returns:
            Tuple of (batch_dict, sample_indices, IS_weights).
            batch_dict has keys: states, actions, rewards, next_states, dones.
        """
        if batch_size > self.size:
            raise ValueError(
                f"Batch size {batch_size} exceeds buffer size {self.size}"
            )

        total_priority = self._tree[0]
        batch_dict: Dict[str, np.ndarray] = {
            "states": [],
            "actions": [],
            "rewards": [],
            "next_states": [],
            "dones": [],
        }
        indices: List[int] = []
        weights: List[float] = []

        segment = total_priority / batch_size
        for i in range(batch_size):
            v = random.uniform(
                segment * i, segment * (i + 1)
            )
            idx, priority, is_weight = self._retrieve(v, 0)
            experience = self.buffer[idx]

            batch_dict["states"].append(experience.state)
            batch_dict["actions"].append(experience.action)
            batch_dict["rewards"].append(experience.reward)
            batch_dict["next_states"].append(experience.next_state)
            batch_dict["dones"].append(experience.done)

            indices.append(idx)
            weights.append(is_weight)

        # Convert lists to numpy arrays
        for key in batch_dict:
            if key in ("states", "next_states"):
                batch_dict[key] = np.array(batch_dict[key])
            else:
                batch_dict[key] = np.array(batch_dict[key])

        self._frame_idx += 1
        # Anneal beta toward 1.0
        self.beta = min(1.0, self.beta + (1.0 - self.beta) / self.beta_frames)

        return batch_dict, np.array(indices), np.array(weights)

    def update_priorities(
        self, indices: np.ndarray, priorities: np.ndarray
    ) -> None:
        """Update priorities after TD error computation.

        Args:
            indices: Buffer indices to update.
            priorities: New priority values (absolute TD errors + epsilon).
        """
        for idx, priority in zip(indices, priorities):
            if 0 <= idx < self.size:
                p = abs(priority) + 1e-8
                self._max_priority = max(self._max_priority, p)
                self._update_tree_idx(int(idx), float(p))
