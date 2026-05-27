"""
Unit Tests — Reinforcement Learning Module.

Tests cover:
    - RewardFunction: P&L, costs, drawdown penalty, Sharpe bonus
    - ExperienceReplayBuffer: push/sample/clear/edge cases
    - PrioritizedReplayBuffer: priority updates, IS weights
    - DuelingDDQNNetwork: forward pass, Q-value shapes, save/load
    - DDQNAgent: action selection, training, epsilon decay, checkpoint
    - TradingEnvironment: reset/step, observation space, rewards, termination
    - TrainingPipeline: data splitting, episode loop, evaluation

Run with: pytest tests/test_rl.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import torch


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def sample_features():
    """Generate synthetic feature data for testing."""
    np.random.seed(42)
    n_steps = 200
    n_features = 11  # OHLCV + RSI + MACD + MACD_sig + BB_upper + BB_lower + ATR
    data = np.random.randn(n_steps, n_features).cumsum(axis=0) + 100.0
    # Ensure Close (col 3) is always positive
    data[:, 3] = np.abs(data[:, 3]) + 10.0
    return data


@pytest.fixture
def sample_ohlcv_simple():
    """Simple OHLCV data with known patterns."""
    dates = np.arange(100)
    close = 100 + np.sin(np.linspace(0, 4 * np.pi, 100)) * 5
    data = np.column_stack([
        close - 0.5,  # Open
        close + 1.0,  # High
        close - 1.0,  # Low
        close,         # Close
        np.random.randint(1000, 5000, 100),  # Volume
    ])
    return data


# ── RewardFunction Tests ───────────────────────────────────────────

class TestRewardFunction:
    """Tests for reward computation."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.reward import RewardConfig, RewardFunction
        assert RewardFunction is not None

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        assert reward_fn.config.commission_rate == 0.001
        assert reward_fn.config.slippage_rate == 0.0005
        assert reward_fn.config.max_drawdown_threshold == 0.15

    def test_reset(self) -> None:
        """Test reset clears state."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)
        assert reward_fn.peak_equity == 10_000.0
        assert len(reward_fn.returns_history) == 0

    def test_positive_pnl_reward(self) -> None:
        """Profit should yield positive reward."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)
        reward, breakdown = reward_fn.compute(
            prev_equity=10_000.0,
            current_equity=10_500.0,
            action=0,  # HOLD
            position_size=0.5,
        )
        assert reward > 0
        assert breakdown["pnl_return"] > 0

    def test_negative_pnl_reward(self) -> None:
        """Loss should yield negative reward."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)
        reward, _ = reward_fn.compute(
            prev_equity=10_000.0,
            current_equity=9_500.0,
            action=0,
            position_size=0.5,
        )
        assert reward < 0

    def test_transaction_cost_on_trade(self) -> None:
        """Trade actions should incur transaction cost."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)

        # BUY action
        _, buy_breakdown = reward_fn.compute(
            prev_equity=10_000.0,
            current_equity=10_000.0,
            action=1,  # BUY
            position_size=0.5,
        )
        assert buy_breakdown["transaction_cost"] > 0

        # HOLD action should have no cost
        _, hold_breakdown = reward_fn.compute(
            prev_equity=10_000.0,
            current_equity=10_000.0,
            action=0,  # HOLD
            position_size=0.5,
        )
        assert hold_breakdown["transaction_cost"] == 0.0

    def test_drawdown_penalty(self) -> None:
        """Exceeding drawdown threshold should add penalty."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)
        # Simulate large drop
        reward, breakdown = reward_fn.compute(
            prev_equity=10_000.0,
            current_equity=8_000.0,  # 20% drawdown > 15% threshold
            action=0,
            position_size=0.5,
        )
        assert breakdown["drawdown_penalty"] < 0

    def test_terminal_bonus(self) -> None:
        """Terminal step should include terminal bonus."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(10_000.0)
        # Build up returns history
        for i in range(30):
            reward_fn.compute(
                prev_equity=10_000.0 + i * 10,
                current_equity=10_000.0 + (i + 1) * 10,
                action=0,
                position_size=0.5,
            )
        reward, breakdown = reward_fn.compute(
            prev_equity=10_300.0,
            current_equity=10_350.0,
            action=0,
            position_size=0.5,
            is_terminal=True,
        )
        assert "terminal_bonus" in breakdown

    def test_simple_reward(self) -> None:
        """Test simplified reward computation."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        # Long position with price increase → positive reward
        r = reward_fn.compute_simple(100.0, 105.0, 1, 1)
        assert r > 0
        # Long position with price decrease → negative reward
        r = reward_fn.compute_simple(100.0, 95.0, 1, 1)
        assert r < 0

    def test_zero_equity_handling(self) -> None:
        """Zero equity should return negative reward."""
        from pipeline.rl.reward import RewardFunction
        reward_fn = RewardFunction()
        reward_fn.reset(0.0)
        reward, breakdown = reward_fn.compute(
            prev_equity=0.0,
            current_equity=0.0,
            action=0,
            position_size=0.0,
        )
        assert reward < 0


# ── ExperienceReplayBuffer Tests ───────────────────────────────────

class TestExperienceReplayBuffer:
    """Tests for replay buffer operations."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        assert ExperienceReplayBuffer is not None

    def test_init(self) -> None:
        """Test initialization with valid capacity."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=1000)
        assert buf.capacity == 1000
        assert buf.size == 0
        assert buf.count == 0

    def test_init_invalid_capacity(self) -> None:
        """Test initialization with invalid capacity."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        with pytest.raises(ValueError):
            ExperienceReplayBuffer(capacity=0)
        with pytest.raises(ValueError):
            ExperienceReplayBuffer(capacity=-1)

    def test_push_and_size(self) -> None:
        """Test push increases buffer size."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        state = np.array([1.0, 2.0, 3.0])
        next_state = np.array([4.0, 5.0, 6.0])

        buf.push(state, 0, 1.0, next_state, False)
        assert buf.size == 1
        assert buf.count == 1

    def test_sample(self) -> None:
        """Test sampling returns correct batch structure."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        for i in range(20):
            state = np.array([float(i), float(i + 1)])
            next_state = np.array([float(i + 1), float(i + 2)])
            buf.push(state, i % 3, float(i), next_state, False)

        batch = buf.sample(10)
        assert "states" in batch
        assert "actions" in batch
        assert "rewards" in batch
        assert "next_states" in batch
        assert "dones" in batch
        assert batch["states"].shape == (10, 2)
        assert batch["actions"].shape == (10,)

    def test_sample_batch_too_large(self) -> None:
        """Sampling more than buffer size should raise."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        state = np.array([1.0, 2.0])
        buf.push(state, 0, 1.0, state, False)

        with pytest.raises(ValueError):
            buf.sample(5)

    def test_sample_invalid_batch_size(self) -> None:
        """Zero or negative batch size should raise."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        for i in range(20):
            s = np.array([float(i)])
            buf.push(s, 0, 0.0, s, False)

        with pytest.raises(ValueError):
            buf.sample(0)
        with pytest.raises(ValueError):
            buf.sample(-1)

    def test_capacity_eviction(self) -> None:
        """Buffer should evict oldest when exceeding capacity."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=5)
        for i in range(10):
            state = np.array([float(i)])
            buf.push(state, 0, float(i), state, False)

        assert buf.size == 5
        assert buf.count == 10

    def test_clear(self) -> None:
        """Clear should empty the buffer."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        for i in range(10):
            s = np.array([float(i)])
            buf.push(s, 0, 0.0, s, False)
        buf.clear()
        assert buf.size == 0

    def test_state_copy(self) -> None:
        """Pushed states should be copied, not referenced."""
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        buf = ExperienceReplayBuffer(capacity=100)
        state = np.array([1.0, 2.0])
        buf.push(state, 0, 1.0, state.copy(), False)
        # Modify original after push
        state[0] = 999.0
        batch = buf.sample(1)
        assert batch["states"][0, 0] == 1.0


# ── PrioritizedReplayBuffer Tests ──────────────────────────────────

class TestPrioritizedReplayBuffer:
    """Tests for prioritized experience replay."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.replay_buffer import PrioritizedReplayBuffer
        assert PrioritizedReplayBuffer is not None

    def test_init(self) -> None:
        """Test initialization with valid parameters."""
        from pipeline.rl.replay_buffer import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=100, alpha=0.6, beta=0.4)
        assert buf.alpha == 0.6
        assert buf.beta == 0.4

    def test_invalid_alpha(self) -> None:
        """Alpha outside [0,1] should raise."""
        from pipeline.rl.replay_buffer import PrioritizedReplayBuffer
        with pytest.raises(ValueError):
            PrioritizedReplayBuffer(alpha=-0.1)
        with pytest.raises(ValueError):
            PrioritizedReplayBuffer(alpha=1.5)

    def test_sample_returns_weights(self) -> None:
        """Sample should return batch, indices, and IS weights."""
        from pipeline.rl.replay_buffer import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=100, alpha=0.6)
        for i in range(30):
            s = np.array([float(i), float(i + 1)])
            buf.push(s, i % 3, float(i), s.copy(), False)

        batch, indices, weights = buf.sample(10)
        assert len(indices) == 10
        assert len(weights) == 10
        assert all(w > 0 for w in weights)

    def test_update_priorities(self) -> None:
        """Priorities should be updated after TD error."""
        from pipeline.rl.replay_buffer import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=100, alpha=0.6)
        for i in range(20):
            s = np.array([float(i)])
            buf.push(s, 0, 0.0, s.copy(), False)

        batch, indices, weights = buf.sample(5)
        new_priorities = np.abs(np.random.randn(5)) + 0.1
        buf.update_priorities(indices, new_priorities)
        # Should not raise


# ── DuelingDDQNNetwork Tests ───────────────────────────────────────

class TestDuelingDDQNNetwork:
    """Tests for the neural network architecture."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        assert DuelingDDQNNetwork is not None

    def test_init(self) -> None:
        """Test initialization with valid parameters."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        net = DuelingDDQNNetwork(state_dim=10, action_dim=3)
        assert net.state_dim == 10
        assert net.action_dim == 3

    def test_invalid_state_dim(self) -> None:
        """Negative state_dim should raise."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        with pytest.raises(ValueError):
            DuelingDDQNNetwork(state_dim=-1, action_dim=3)

    def test_invalid_action_dim(self) -> None:
        """Zero action_dim should raise."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        with pytest.raises(ValueError):
            DuelingDDQNNetwork(state_dim=10, action_dim=0)

    def test_forward_pass(self) -> None:
        """Forward pass should produce correct output shape."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        net = DuelingDDQNNetwork(state_dim=20, action_dim=3)
        batch = torch.randn(8, 20)
        output = net(batch)
        assert output.shape == (8, 3)

    def test_single_state_forward(self) -> None:
        """Single state input should work."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        net = DuelingDDQNNetwork(state_dim=20, action_dim=3)
        state = torch.randn(20)
        # Single state needs batch dim for forward
        output = net(state.unsqueeze(0))
        assert output.shape == (1, 3)

    def test_get_q_values_numpy(self) -> None:
        """get_q_values should accept numpy arrays."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        net = DuelingDDQNNetwork(state_dim=20, action_dim=3)
        state = np.random.randn(20).astype(np.float32)
        q_np, q_torch = net.get_q_values(state)
        assert q_np.shape == (3,)
        assert torch.is_tensor(q_torch)

    def test_save_load(self) -> None:
        """Save and load should preserve weights."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        with tempfile.NamedTemporaryFile(suffix=".pth", delete=False) as f:
            path = f.name

        try:
            net1 = DuelingDDQNNetwork(state_dim=10, action_dim=3)
            net1.save(path)

            net2 = DuelingDDQNNetwork(state_dim=10, action_dim=3)
            net2.load(path)

            # Compare outputs
            state = torch.randn(5, 10)
            out1 = net1(state)
            out2 = net2(state)
            assert torch.allclose(out1, out2, atol=1e-6)
        finally:
            os.unlink(path)

    def test_dropout_initialization(self) -> None:
        """Network with dropout should initialize without error."""
        from pipeline.rl.networks import DuelingDDQNNetwork
        net = DuelingDDQNNetwork(state_dim=10, action_dim=3, dropout_rate=0.1)
        output = net(torch.randn(4, 10))
        assert output.shape == (4, 3)


# ── DDQNAgent Tests ────────────────────────────────────────────────

class TestDDQNAgent:
    """Tests for the DDQN agent."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.agent import AgentConfig, DDQNAgent
        assert DDQNAgent is not None

    def test_init(self) -> None:
        """Test initialization with default config."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=20, action_dim=3)
        assert agent.state_dim == 20
        assert agent.action_dim == 3
        assert agent.epsilon == 1.0

    def test_select_action_exploration(self) -> None:
        """With epsilon=1.0, actions should be random."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=20, action_dim=3)
        state = np.random.randn(20).astype(np.float32)

        actions = [agent.select_action(state) for _ in range(100)]
        # With pure exploration, should see all actions
        assert len(set(actions)) > 1

    def test_select_action_deterministic(self) -> None:
        """Deterministic mode should always return same action."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=20, action_dim=3)
        state = np.random.randn(20).astype(np.float32)

        actions = [
            agent.select_action(state, deterministic=True)
            for _ in range(10)
        ]
        assert len(set(actions)) == 1

    def test_epsilon_decay(self) -> None:
        """Epsilon should decrease over time."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=20, action_dim=3)
        initial_epsilon = agent.epsilon

        for _ in range(100):
            agent.decay_epsilon()

        assert agent.epsilon < initial_epsilon
        assert agent.epsilon >= agent.config.epsilon_min

    def test_train_insufficient_data(self) -> None:
        """Training with insufficient data should return None."""
        from pipeline.rl.agent import DDQNAgent
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        agent = DDQNAgent(state_dim=10, action_dim=3)
        buf = ExperienceReplayBuffer(capacity=1000)

        loss = agent.train(buf)
        assert loss is None

    def test_train_with_data(self) -> None:
        """Training with sufficient data should return loss."""
        from pipeline.rl.agent import DDQNAgent, AgentConfig
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer

        config = AgentConfig(warmup_steps=0, batch_size=8)
        agent = DDQNAgent(state_dim=10, action_dim=3, config=config)
        buf = ExperienceReplayBuffer(capacity=1000)

        # Fill buffer
        for i in range(50):
            s = np.random.randn(10).astype(np.float32)
            ns = np.random.randn(10).astype(np.float32)
            buf.push(s, i % 3, float(i), ns, False)

        loss = agent.train(buf)
        assert loss is not None
        assert isinstance(loss, float)

    def test_get_q_values(self) -> None:
        """get_q_values should return array of correct shape."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=20, action_dim=3)
        state = np.random.randn(20).astype(np.float32)
        q_vals = agent.get_q_values(state)
        assert q_vals.shape == (3,)

    def test_save_load(self) -> None:
        """Save and load should preserve agent state."""
        from pipeline.rl.agent import DDQNAgent
        agent = DDQNAgent(state_dim=10, action_dim=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent.save(tmpdir)
            assert Path(f"{tmpdir}/online_net.pth").exists()
            assert Path(f"{tmpdir}/agent_state.pth").exists()

            agent2 = DDQNAgent(state_dim=10, action_dim=3)
            agent2.load(tmpdir)

            # Compare Q-values
            state = np.random.randn(10).astype(np.float32)
            q1 = agent.get_q_values(state)
            q2 = agent2.get_q_values(state)
            assert np.allclose(q1, q2, atol=1e-5)


# ── TradingEnvironment Tests ───────────────────────────────────────

class TestTradingEnvironment:
    """Tests for the Gym-compatible trading environment."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.environment import EnvironmentConfig, TradingEnvironment
        assert TradingEnvironment is not None

    def test_init(self, sample_features):
        """Test initialization with valid data."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        assert env.action_space.n == 3
        assert env.observation_space.shape[0] > 0

    def test_insufficient_data(self):
        """Data shorter than state_window should raise."""
        from pipeline.rl.environment import TradingEnvironment
        short_data = np.random.randn(5, 5)
        with pytest.raises(ValueError):
            TradingEnvironment(short_data)

    def test_reset(self, sample_features):
        """Reset should return valid observation."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, info = env.reset()
        assert obs.shape == env.observation_space.shape
        assert isinstance(info, dict)

    def test_reset_with_seed(self, sample_features):
        """Reset with seed should be reproducible."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs1, _ = env.reset(seed=42)
        obs2, _ = env.reset(seed=42)
        assert np.allclose(obs1, obs2)

    def test_step_returns(self, sample_features):
        """Step should return correct tuple structure."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, _ = env.reset()
        next_obs, reward, terminated, truncated, info = env.step(0)

        assert next_obs.shape == obs.shape
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert "reward_breakdown" in info

    def test_hold_action(self, sample_features):
        """HOLD action should not change position."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, _ = env.reset()
        _, _, _, _, info = env.step(0)
        assert info["position"] == 0

    def test_buy_action(self, sample_features):
        """BUY action should open long position."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, _ = env.reset()
        _, _, _, _, info = env.step(1)
        assert info["position"] == 1

    def test_sell_closes_position(self, sample_features):
        """SELL after BUY should close position."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, _ = env.reset()
        _, _, _, _, _ = env.step(1)  # BUY
        _, _, _, _, info = env.step(2)  # SELL
        assert info["position"] == 0

    def test_termination(self, sample_features):
        """Environment should terminate at data end."""
        from pipeline.rl.environment import TradingEnvironment
        # Use small window to reach end quickly
        from pipeline.rl.environment import EnvironmentConfig
        config = EnvironmentConfig(state_window=5, max_steps=500)
        env = TradingEnvironment(sample_features, config)
        obs, _ = env.reset()

        terminated = False
        steps = 0
        while not terminated and steps < 1000:
            obs, _, terminated, truncated, _ = env.step(0)
            steps += 1

        assert terminated or truncated

    def test_episode_stats(self, sample_features):
        """get_episode_stats should return valid metrics."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs, _ = env.reset()

        for _ in range(20):
            obs, _, terminated, truncated, _ = env.step(0)
            if terminated or truncated:
                break

        stats = env.get_episode_stats()
        assert "total_return" in stats
        assert "sharpe_ratio" in stats
        assert "max_drawdown" in stats
        assert "final_equity" in stats

    def test_custom_start_index(self, sample_features):
        """Reset with start_index should begin at specified position."""
        from pipeline.rl.environment import TradingEnvironment
        env = TradingEnvironment(sample_features)
        obs1, _ = env.reset()
        obs2, _ = env.reset(options={"start_index": 10})
        # Observations should differ
        assert not np.allclose(obs1, obs2)


# ── TrainingPipeline Tests ─────────────────────────────────────────

class TestTrainingPipeline:
    """Tests for the training pipeline."""

    def test_import(self) -> None:
        """Verify module imports successfully."""
        from pipeline.rl.training import TrainingConfig, TrainingPipeline
        assert TrainingPipeline is not None

    def test_init(self, sample_features):
        """Test initialization with valid data."""
        from pipeline.rl.training import TrainingConfig, TrainingPipeline
        config = TrainingConfig(n_episodes=5)
        pipeline = TrainingPipeline(sample_features, config)
        assert len(pipeline.train_data) > 0
        assert len(pipeline.val_data) > 0

    def test_data_splitting(self, sample_features):
        """Data should be split according to train_ratio."""
        from pipeline.rl.training import TrainingConfig, TrainingPipeline
        n = len(sample_features)
        config = TrainingConfig(train_ratio=0.8)
        pipeline = TrainingPipeline(sample_features, config)

        expected_train = int(n * 0.8)
        assert len(pipeline.train_data) == expected_train
        assert len(pipeline.val_data) == n - expected_train

    def test_short_training(self, sample_features):
        """Training should complete without error."""
        from pipeline.rl.training import TrainingConfig, TrainingPipeline
        from pipeline.rl.agent import AgentConfig
        from pipeline.rl.environment import EnvironmentConfig

        agent_cfg = AgentConfig(
            warmup_steps=0,
            batch_size=8,
            epsilon_start=0.5,
            epsilon_decay=0.9,
        )
        env_cfg = EnvironmentConfig(state_window=5, max_steps=50)
        config = TrainingConfig(
            n_episodes=3,
            eval_interval=2,
            agent_config=agent_cfg,
            env_config=env_cfg,
        )

        pipeline = TrainingPipeline(sample_features, config)
        metrics = pipeline.train()

        assert len(metrics.episode_rewards) == 3
        assert metrics.total_training_time > 0

    def test_predict(self, sample_features):
        """Predict should return list of actions."""
        from pipeline.rl.training import TrainingConfig, TrainingPipeline
        from pipeline.rl.agent import AgentConfig
        from pipeline.rl.environment import EnvironmentConfig

        agent_cfg = AgentConfig(warmup_steps=0, batch_size=4)
        env_cfg = EnvironmentConfig(state_window=5, max_steps=30)
        config = TrainingConfig(
            n_episodes=1,
            agent_config=agent_cfg,
            env_config=env_cfg,
        )

        pipeline = TrainingPipeline(sample_features, config)
        actions = pipeline.predict(sample_features[:50])
        assert len(actions) > 0
        assert all(a in (0, 1, 2) for a in actions)


# ── Integration Tests ──────────────────────────────────────────────

class TestRLIntegration:
    """End-to-end integration tests."""

    def test_full_training_loop(self):
        """Complete training cycle with all components."""
        from pipeline.rl.agent import AgentConfig, DDQNAgent
        from pipeline.rl.environment import EnvironmentConfig, TradingEnvironment
        from pipeline.rl.replay_buffer import ExperienceReplayBuffer
        from pipeline.rl.reward import RewardFunction

        # Generate data
        np.random.seed(42)
        data = np.random.randn(100, 6).cumsum(axis=0) + 100.0
        data[:, 3] = np.abs(data[:, 3]) + 10.0  # Close > 0

        # Setup components
        env_cfg = EnvironmentConfig(state_window=5, max_steps=80)
        agent_cfg = AgentConfig(warmup_steps=5, batch_size=8)
        env = TradingEnvironment(data, env_cfg)
        agent = DDQNAgent(
            state_dim=env_cfg.state_window * data.shape[1],
            action_dim=3,
            config=agent_cfg,
        )
        buf = ExperienceReplayBuffer(capacity=1000)
        reward_fn = RewardFunction()

        # Run mini episode
        obs, _ = env.reset()
        total_reward = 0.0

        for _ in range(30):
            action = agent.select_action(obs)
            next_obs, reward, terminated, truncated, info = env.step(action)
            agent.store_transition(obs, action, reward, next_obs, terminated, buf)
            loss = agent.train(buf)
            agent.decay_epsilon()
            total_reward += reward
            obs = next_obs
            if terminated or truncated:
                break

        # Verify
        assert buf.size > 0
        assert agent.step_count == 0  # Not incremented in this test
        stats = env.get_episode_stats()
        assert stats["n_steps"] > 0

    def test_reward_consistency_across_episode(self):
        """Rewards should be consistent with equity changes."""
        from pipeline.rl.environment import TradingEnvironment
        np.random.seed(123)
        data = np.random.randn(50, 6).cumsum(axis=0) + 100.0
        data[:, 3] = np.abs(data[:, 3]) + 10.0

        env = TradingEnvironment(data)
        obs, _ = env.reset()
        rewards = []

        for _ in range(20):
            obs, reward, terminated, truncated, info = env.step(0)
            rewards.append(reward)
            if terminated or truncated:
                break

        assert len(rewards) > 0
        # All rewards should be finite
        assert all(np.isfinite(r) for r in rewards)
