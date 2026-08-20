from typing import Dict, Any, List
from .base_agent import BaseAgent
from .committee import TechnicalAgent, FundamentalAgent, SentimentAgent, MacroAgent, RiskAgent, VolatilityAgent, LiquidityAgent, CorrelationAgent

# torch is OPTIONAL: if it is missing the agent degrades to WAIT signals
# instead of crashing at import time.
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    nn = None
    F = None
    optim = None
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:

    class MasterPolicyNet(nn.Module):
        def __init__(self, input_dim: int, hidden_dim: int = 64, num_actions: int = 3):
            super(MasterPolicyNet, self).__init__()
            # State vector: committee votes (4 agents * 1 signal), plus regime vector, plus LSTM signal
            self.fc1 = nn.Linear(input_dim, hidden_dim)
            self.fc2 = nn.Linear(hidden_dim, hidden_dim)
            self.action_head = nn.Linear(hidden_dim, num_actions)
            self.value_head = nn.Linear(hidden_dim, 1)

        def forward(self, x):
            x = F.relu(self.fc1(x))
            x = F.relu(self.fc2(x))

            action_logits = self.action_head(x)
            state_value = self.value_head(x)

            return F.softmax(action_logits, dim=-1), state_value
else:
    MasterPolicyNet = None  # type: ignore[assignment,misc]

class PPOMasterAgent(BaseAgent):
    """
    Tier 3: PPO Master Agent.
    Replaces static weight-scaling logic with a deep policy gradient network.
    Action Space: 0 = SELL, 1 = WAIT, 2 = BUY
    
    CRITICAL ARCHITECTURAL NOTE:
    Policy gradient models like PPO require thousands of complete trajectory rollouts 
    to update weights effectively. In live trading, the low frequency of closed trades 
    (3-5 per day) makes on-line training insufficient. Thus, this agent runs in 
    INFERENCE mode and should be treated as a secondary/shadow orchestrator unless 
    pre-trained offline in backtesting simulation with 500+ trajectory samples.
    """
    def __init__(self, input_dim: int = 9):
        super().__init__("Deep RL Master Agent (PPO)")
        self.policy = None
        self.optimizer = None
        self.is_trained = False
        if TORCH_AVAILABLE:
            self.device = torch.device("cpu")
            self.policy = MasterPolicyNet(input_dim=input_dim).to(self.device)
            self.optimizer = optim.Adam(self.policy.parameters(), lr=0.001)
        self.load_policy_weights()

    def load_policy_weights(self):
        import os
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "data", "ppo_policy.pth")
        if TORCH_AVAILABLE and os.path.exists(path):
            try:
                self.policy.load_state_dict(torch.load(path, map_location=self.device))
                self.policy.eval()
                self.is_trained = True
                print(f"[PPOMasterAgent] Loaded pre-trained policy weights from {path}")
            except Exception as e:
                print(f"[PPOMasterAgent] Error loading policy weights: {e}")

        self.committee: List[BaseAgent] = [
            TechnicalAgent(),
            FundamentalAgent(),
            SentimentAgent(),
            MacroAgent(),
            VolatilityAgent(),
            LiquidityAgent(),
            CorrelationAgent()
        ]
        self.risk_manager = RiskAgent()
        
    def _encode_state(self, committee_results: List[Dict], data: Dict[str, Any]):
        # Encode votes scaled by confidence: -confidence for SELL, 0.0 for WAIT, +confidence for BUY
        vote_map = {"SELL": -1.0, "WAIT": 0.0, "BUY": 1.0}
        state_features = []
        for res in committee_results:
            vote_val = vote_map.get(res["signal"], 0.0)
            confidence = res.get("confidence", 1.0)
            state_features.append(vote_val * confidence)
            
        # Add regime feature (dummy encoding for simplicity)
        regime = data.get("regime", "Sideways")
        regime_map = {
            "Trending Bull": 1.0,
            "Sideways": 0.0,
            "Trending Bear": -1.0,
            "High Volatility": 0.5,
            "Strong Trend Bull": 1.0, "Weak Trend Bull": 0.5, 
            "Strong Trend Bear": -1.0, "Weak Trend Bear": -0.5, 
            "Expansion": 0.8, "News Shock": -0.8, "High Liquidity": 0.3, 
            "Low Liquidity": -0.3, "Gap Day": 0.0, "Compression": 0.0
        }
        regime_val = regime_map.get(regime, 0.0)
        state_features.append(regime_val)
        
        # Add LSTM signal scaled by confidence if available
        lstm_signal = data.get("lstm_signal", "WAIT")
        lstm_confidence = data.get("lstm_confidence", 1.0)
        state_features.append(vote_map.get(lstm_signal, 0.0) * lstm_confidence)
        
        return torch.tensor([state_features], dtype=torch.float32).to(self.device)

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        results = []
        agent_weights = data.get("agent_weights", {})
        for agent in self.committee:
            vote = agent.evaluate(symbol, data)
            weight = agent_weights.get(agent.name, 1.0)
            sig_val = 1.0 if vote["signal"] == "BUY" else -1.0 if vote["signal"] == "SELL" else 0.0
            contribution = round(sig_val * vote["confidence"] * weight, 3)
            results.append({
                "agent": agent.name,
                "signal": vote["signal"],
                "confidence": vote["confidence"],
                "reason": vote["reason"],
                "weight": round(weight, 3),
                "contribution": contribution
            })
            
        # An UNTRAINED policy network produces arbitrary (randomly initialized)
        # actions — never trade on it. Same if torch is unavailable.
        if not TORCH_AVAILABLE or not self.is_trained:
            reason = ("PPO disabled (torch not installed)" if not TORCH_AVAILABLE
                      else "PPO policy untrained (no checkpoint at data/ppo_policy.pth)")
            return {
                "signal": "WAIT",
                "confidence": 0.0,
                "reason": reason,
                "committee_breakdown": results,
                "regime": data.get("regime", "Sideways")
            }

        state_tensor = self._encode_state(results, data)

        with torch.no_grad():
            action_probs, state_value = self.policy(state_tensor)
            
        # Select action greedily for paper trading stability (instead of purely stochastic)
        # In a real training environment, we would sample:
        # action_dist = torch.distributions.Categorical(action_probs)
        # action = action_dist.sample().item()
        action = torch.argmax(action_probs, dim=1).item()
        
        action_map = {0: "SELL", 1: "WAIT", 2: "BUY"}
        final_signal = action_map[action]
        final_confidence = action_probs[0][action].item()
        
        # Risk Manager Check
        if final_signal != "WAIT":
            risk_vote = self.risk_manager.evaluate(symbol, data)
            if risk_vote["signal"] == "VETO":
                return {
                    "signal": "WAIT",
                    "confidence": final_confidence,
                    "reason": f"PPO Agent initiated {final_signal}, but Risk Manager VETOED: {risk_vote['reason']}",
                    "committee_breakdown": results
                }
                
        return {
            "signal": final_signal,
            "confidence": round(final_confidence, 2),
            "reason": f"PPO Policy Network activated with state value {state_value.item():.2f}",
            "committee_breakdown": results,
            "regime": data.get("regime", "Sideways")
        }
