from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseAgent(ABC):
    """
    Abstract base class for all trading AI committee members.
    Every specialized agent must implement the evaluate() method
    to return a unified trade signal, confidence score, and rationale.
    """
    
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate market data for a given symbol.
        
        Returns:
            Dict containing:
            - signal (str): "BUY", "SELL", or "WAIT"
            - confidence (float): 0.0 to 1.0 score
            - reason (str): Human-readable logic for Explainable AI
        """
        pass
