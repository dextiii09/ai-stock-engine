import os
import json
import numpy as np
from typing import Dict, Any, List

class CausalAttributionEngine:
    """
    Analyzes historical trade outcomes and matches them with entry decisions
    to calculate sub-agent and feature level attribution.
    """
    def __init__(self, journal_path: str = "journal.json", portfolio_path: str = "data/portfolio_state.json"):
        # Resolve paths relative to the backend directory
        base_dir = os.path.join(os.path.dirname(__file__), "..")
        self.journal_path = os.path.join(base_dir, journal_path)
        self.portfolio_path = os.path.join(base_dir, portfolio_path)

    def _load_data(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        journal = []
        closed_trades = []
        
        if os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, "r") as f:
                    journal = json.load(f)
            except Exception as e:
                print(f"[Attribution] Error loading journal: {e}")
                
        if os.path.exists(self.portfolio_path):
            try:
                with open(self.portfolio_path, "r") as f:
                    state = json.load(f)
                    closed_trades = state.get("closed_trades", [])
            except Exception as e:
                print(f"[Attribution] Error loading portfolio state: {e}")
                
        return journal, closed_trades

    def analyze(self, journal: List[Dict[str, Any]] = None, closed_trades: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Treat empty lists the same as None — fall back to disk so restart doesn't
        # wipe historical attribution until new trades close.
        if not journal or not closed_trades:
            file_journal, file_closed = self._load_data()
            if not journal:
                journal = file_journal
            if not closed_trades:
                closed_trades = file_closed
        
        if not closed_trades:
            return {
                "status": "No closed trades available for attribution analysis.",
                "agent_attribution": {},
                "feature_correlation": {}
            }
            
        # Match closed trades with entry journal logs
        matched_trades = []
        buy_logs = [log for log in journal if log.get("action") == "BUY"]
        
        for trade in closed_trades:
            trade_time = trade.get("time", 0)
            symbol = trade.get("symbol")
            
            # Find the closest BUY log before this trade's close time
            best_match = None
            min_diff = float("inf")
            
            for log in buy_logs:
                log_time = log.get("timestamp", 0)
                if log.get("symbol") == symbol and log_time < trade_time:
                    diff = trade_time - log_time
                    if diff < min_diff:
                        min_diff = diff
                        best_match = log
                        
            if best_match:
                matched_trades.append({
                    "trade": trade,
                    "entry_log": best_match
                })

        if not matched_trades:
            return {
                "status": "Could not match closed trades with entry journal logs.",
                "agent_attribution": {},
                "feature_correlation": {}
            }

        # 1. Agent Attribution Calculations
        # Mapping vote signal to numeric scale
        signal_map = {"BUY": 1.0, "SELL": -1.0, "WAIT": 0.0}
        agent_raw_attributions = {}  # agent_name -> list of (vote * return)
        
        for matched in matched_trades:
            ret = matched["trade"].get("return_pct") or matched["trade"].get("profit_pct", 0.0)
            breakdown = matched["entry_log"].get("committee_breakdown", [])
            
            for vote in breakdown:
                agent = vote.get("agent")
                sig = vote.get("signal", "WAIT")
                vote_val = signal_map.get(sig, 0.0)
                
                # Causal attribution formula: vote_direction * profit_pct
                attr = vote_val * ret
                
                if agent not in agent_raw_attributions:
                    agent_raw_attributions[agent] = []
                agent_raw_attributions[agent].append(attr)

        agent_attribution = {}
        for agent, attrs in agent_raw_attributions.items():
            agent_attribution[agent] = {
                "total_attribution": round(float(sum(attrs)), 3),
                "avg_attribution": round(float(np.mean(attrs)), 3),
                "num_trades": len(attrs)
            }

        # 2. Feature Attribution Calculations (Correlation with profit_pct)
        feature_data = {}  # feature_name -> list of values
        returns = []
        
        for matched in matched_trades:
            ret = matched["trade"].get("return_pct") or matched["trade"].get("profit_pct", 0.0)
            features = matched["entry_log"].get("entry_features")
            
            if not features:
                continue
                
            returns.append(ret)
            for feat, val in features.items():
                if val is None:
                    continue
                if feat not in feature_data:
                    feature_data[feat] = []
                feature_data[feat].append(val)

        feature_correlation = {}
        # We need at least 2 matched samples with features to compute correlation
        if len(returns) >= 2:
            for feat, vals in feature_data.items():
                if len(vals) == len(returns):
                    # Standard Pearson correlation coefficient
                    std_feat = np.std(vals)
                    std_ret = np.std(returns)
                    
                    if std_feat > 0 and std_ret > 0:
                        corr = np.corrcoef(vals, returns)[0, 1]
                        if not np.isnan(corr):
                            feature_correlation[feat] = round(float(corr), 3)
                    else:
                        feature_correlation[feat] = 0.0

        return {
            "status": "success",
            "total_analyzed_trades": len(matched_trades),
            "agent_attribution": agent_attribution,
            "feature_correlation": feature_correlation
        }
