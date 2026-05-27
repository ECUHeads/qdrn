"""
Reinforcement Learning Module — DRL Trading Agent Core.

Implements Deep Q-Network (DQN), Double DQN (DDQN), and Dueling Network
architectures for automated trading decision-making.

Components:
    - environment.py: Gym-compatible TradingEnvironment
    - replay_buffer.py: Experience Replay Buffer with prioritized sampling
    - reward.py: Reward function engineering (P&L, costs, drawdown penalty)
    - networks.py: Dueling DDQN neural network architecture
    - agent.py: DDQN Agent with epsilon-greedy exploration
    - training.py: Training pipeline with walk-forward validation
"""

from pipeline.rl.agent import DDQNAgent
from pipeline.rl.environment import TradingEnvironment
from pipeline.rl.networks import DuelingDDQNNetwork
from pipeline.rl.replay_buffer import ExperienceReplayBuffer
from pipeline.rl.reward import RewardFunction

__all__ = [
    "DDQNAgent",
    "DuelingDDQNNetwork",
    "ExperienceReplayBuffer",
    "RewardFunction",
    "TradingEnvironment",
]
