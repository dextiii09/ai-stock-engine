import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
from typing import List, Dict, Any

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from agents.ppo_master import PPOMasterAgent
from data.provider import DataProviderFactory
from backtesting.engine import compute_indicators
from data.regime_detector import MarketRegimeDetector
from analytics.lstm_model import LSTMSignalEngine

def run_ppo_pretraining(epochs=5, learning_rate=0.001, clip_eps=0.2):
    print("=== Starting PPO Offline Pre-training Harness ===")
    
    # 1. Download 1 year of daily historical data for MNQ=F
    provider = DataProviderFactory.get_provider()
    try:
        print("[PPO Train] Downloading historical data for MNQ=F...")
        df_raw = provider.get_historical_ohlcv("MNQ=F", period="1y", interval="1d")
        df = compute_indicators(df_raw.copy())
        print(f"[PPO Train] Ingested {len(df)} historical data points.")
    except Exception as e:
        print(f"[PPO Train] Ingestion failed: {e}. Cannot train PPO agent offline.")
        return
        
    # Initialize components
    agent = PPOMasterAgent()
    regime_detector = MarketRegimeDetector()
    lstm_engine = LSTMSignalEngine()
    
    # Optimizer for PPO
    optimizer = optim.Adam(agent.policy.parameters(), lr=learning_rate)
    
    # Storage for rollouts
    states = []
    actions = []
    log_probs = []
    rewards = []
    values = []
    
    position = None  # None or Dict{"entry_price", "entry_index"}
    trade_starts = [] # keep track of indices of actions belonging to current trade
    
    # Set model to train mode
    agent.policy.train()
    
    print("[PPO Train] Running simulation to collect rollouts...")
    for idx, (ts, row) in enumerate(df.iterrows()):
        # Construct tick data
        tick_data = {
            "symbol": "MNQ=F",
            "price": float(row["Close"]),
            "rsi_14": float(row["rsi"]),
            "macd_hist": float(row["macd_hist"]),
            "atr_14": float(row["atr"]) if "atr" in row else float(row["Close"]) * 0.01,
            "vwap": float(row["Close"]),  # proxy
            "agent_weights": {a.name: 1.0 for a in agent.committee}
        }
        
        # Detect regime
        regime = regime_detector.detect("MNQ=F", tick_data)
        tick_data["regime"] = regime
        
        # Get LSTM predictions
        lstm_engine.update_tick("MNQ=F", tick_data)
        lstm_sig = lstm_engine.get_signal("MNQ=F")
        tick_data["lstm_signal"] = lstm_sig["signal"]
        tick_data["lstm_confidence"] = lstm_sig["confidence"]
        
        # Collect committee votes to generate PPO state representation
        results = []
        for c_agent in agent.committee:
            vote = c_agent.evaluate("MNQ=F", tick_data)
            results.append(vote)
            
        state_tensor = agent._encode_state(results, tick_data)
        states.append(state_tensor)
        
        # Forward pass through policy
        action_probs, val = agent.policy(state_tensor)
        values.append(val.item())
        
        # Sample action stochastically during training
        action_dist = torch.distributions.Categorical(action_probs)
        action = action_dist.sample()
        actions.append(action.item())
        log_probs.append(action_dist.log_prob(action).item())
        
        # Environment step / Reward calculation
        current_price = float(row["Close"])
        reward = 0.0
        
        # Exit check
        if position is not None:
            # Sizing exit by index end or stop/target
            stop_hit = current_price <= position["stop"]
            tp_hit = current_price >= position["target"]
            end_of_data = idx == len(df) - 1
            
            if stop_hit or tp_hit or end_of_data:
                exit_price = position["stop"] if stop_hit else (position["target"] if tp_hit else current_price)
                pnl_pct = (exit_price / position["entry_price"] - 1.0) * 100.0
                
                # Distribute reward to all steps inside this trade trajectory
                # Settle win rewards
                for step_idx in trade_starts:
                    rewards[step_idx] = pnl_pct / len(trade_starts)
                
                position = None
                trade_starts = []
        
        # Settle step reward
        rewards.append(0.0) # populated on trade close
        
        # Entry check
        if position is None and action.item() == 2:  # BUY
            atr = float(row["atr"]) if "atr" in row else current_price * 0.01
            position = {
                "entry_price": current_price,
                "stop": current_price - 2.0 * atr,
                "target": current_price + 4.0 * atr
            }
            trade_starts.append(idx)
        elif position is not None:
            trade_starts.append(idx)
            
    # Calculate returns and advantages
    states_t = torch.cat(states, dim=0)
    actions_t = torch.tensor(actions, dtype=torch.long)
    log_probs_old = torch.tensor(log_probs, dtype=torch.float32)
    values_t = torch.tensor(values, dtype=torch.float32)
    
    # Compute discounted rewards-to-go / advantages
    discounted_rewards = []
    cumulative_reward = 0.0
    for r in reversed(rewards):
        # We model trade outcomes as episodic returns
        cumulative_reward = r + 0.95 * cumulative_reward
        discounted_rewards.insert(0, cumulative_reward)
        
    returns_t = torch.tensor(discounted_rewards, dtype=torch.float32)
    # Standardize returns
    if len(returns_t) > 1:
        returns_t = (returns_t - returns_t.mean()) / (returns_t.std() + 1e-8)
    advantages_t = returns_t - values_t
    
    # 2. PPO Optimization Epochs
    print(f"[PPO Train] Running {epochs} policy gradient epochs over {len(states_t)} rollouts...")
    for epoch in range(epochs):
        action_probs, state_values = agent.policy(states_t)
        action_dist = torch.distributions.Categorical(action_probs)
        
        log_probs_new = action_dist.log_prob(actions_t)
        entropy = action_dist.entropy().mean()
        
        ratios = torch.exp(log_probs_new - log_probs_old)
        
        surr1 = ratios * advantages_t
        surr2 = torch.clamp(ratios, 1.0 - clip_eps, 1.0 + clip_eps) * advantages_t
        
        policy_loss = -torch.min(surr1, surr2).mean()
        value_loss = nn.MSELoss()(state_values.squeeze(), returns_t)
        
        # PPO Total Loss
        loss = policy_loss + 0.5 * value_loss - 0.01 * entropy
        
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        
        print(f"  Epoch {epoch+1}/{epochs} | Policy Loss: {policy_loss.item():.4f} | Value Loss: {value_loss.item():.4f} | Entropy: {entropy.item():.4f}")
        
    # Save the pre-trained weights
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ppo_policy.pth")
    
    torch.save(agent.policy.state_dict(), out_path)
    print(f"[PPO Train] Pre-training complete! Policy weights saved to {os.path.abspath(out_path)}")

if __name__ == "__main__":
    run_ppo_pretraining()
