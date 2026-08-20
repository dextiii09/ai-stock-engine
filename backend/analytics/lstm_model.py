"""
Tier 3: LSTM Tick Model.

Provides sequence learning beyond static RSI/MACD thresholds.
Maintains a rolling 20-tick buffer to predict the next price direction.

Robustness notes (v3.7):
- torch is an OPTIONAL dependency. If it is not installed the engine
  degrades gracefully to WAIT signals instead of crashing the backend
  at import time.
- The model only emits BUY/SELL signals when a TRAINED checkpoint is
  loaded from data/models/lstm_tick.pt. A freshly initialized (random)
  network previously emitted spurious signals with confidence > 0.55;
  now an untrained model always returns WAIT.
"""

import os
from typing import List, Dict, Any

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:  # torch not installed — degrade gracefully
    torch = None
    nn = None
    F = None
    TORCH_AVAILABLE = False

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKPOINT_PATH = os.path.join(_BASE_DIR, "data", "models", "lstm_tick.pt")

if TORCH_AVAILABLE:

    class TickLSTM(nn.Module):
        def __init__(self, input_size=4, hidden_size=32, num_layers=1, num_classes=3):
            super(TickLSTM, self).__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
            self.fc = nn.Linear(hidden_size, num_classes)

        def forward(self, x):
            h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
            c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)

            out, _ = self.lstm(x, (h0, c0))
            out = out[:, -1, :]
            out = self.fc(out)
            return out
else:
    TickLSTM = None  # type: ignore[assignment,misc]


class LSTMSignalEngine:
    """
    Tier 3: LSTM Tick Model.
    Provides sequence learning beyond static RSI/MACD thresholds.
    Maintains a rolling 20-tick buffer to predict the next price direction.

    Emits real signals only when torch is available AND a trained
    checkpoint has been loaded; otherwise returns WAIT.
    """

    def __init__(self, checkpoint_path: str = CHECKPOINT_PATH):
        self.sequence_buffer: Dict[str, List[Dict[str, float]]] = {"MGC=F": [], "MNQ=F": []}
        self.seq_len = 20
        self.model = None
        self.is_trained = False

        if not TORCH_AVAILABLE:
            return

        self.device = torch.device("cpu")
        self.model = TickLSTM(input_size=4, hidden_size=32, num_layers=1, num_classes=3).to(self.device)
        self.model.eval()

        # Only trust the network if trained weights exist on disk.
        if checkpoint_path and os.path.exists(checkpoint_path):
            try:
                state = torch.load(checkpoint_path, map_location=self.device)
                self.model.load_state_dict(state)
                self.model.eval()
                self.is_trained = True
            except Exception:
                # Corrupt/incompatible checkpoint — stay in WAIT mode.
                self.is_trained = False

    def update_tick(self, symbol: str, tick_data: Dict[str, Any]):
        vwap = tick_data.get("vwap", 1.0)
        vwap = vwap if vwap > 0 else 1.0

        features = {
            "rsi_14": tick_data.get("rsi_14", 50.0) / 100.0,
            "atr_14": tick_data.get("atr_14", 1.0) / 10.0,
            "macd_hist": tick_data.get("macd_hist", 0.0),
            "vwap_dist": (tick_data.get("price", 1.0) - vwap) / vwap,
        }

        if symbol not in self.sequence_buffer:
            self.sequence_buffer[symbol] = []

        self.sequence_buffer[symbol].append(features)
        if len(self.sequence_buffer[symbol]) > self.seq_len:
            self.sequence_buffer[symbol].pop(0)

    def get_signal(self, symbol: str) -> Dict[str, Any]:
        if not TORCH_AVAILABLE:
            return {"signal": "WAIT", "confidence": 0.0,
                    "reason": "LSTM disabled (torch not installed)"}
        if not self.is_trained:
            return {"signal": "WAIT", "confidence": 0.0,
                    "reason": "LSTM untrained (no checkpoint at data/models/lstm_tick.pt)"}

        buffer = self.sequence_buffer.get(symbol, [])
        if len(buffer) < self.seq_len:
            return {"signal": "WAIT", "confidence": 0.0,
                    "reason": f"LSTM buffer warming up ({len(buffer)}/{self.seq_len})"}

        seq = [[b["rsi_14"], b["atr_14"], b["macd_hist"], b["vwap_dist"]] for b in buffer]
        x = torch.tensor([seq], dtype=torch.float32).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = F.softmax(logits, dim=1).squeeze().tolist()

        # Classes: 0: Down (SELL), 1: Flat (WAIT), 2: Up (BUY)
        predicted_class = int(np.argmax(probs))
        confidence = probs[predicted_class]

        if predicted_class == 2 and confidence > 0.55:
            return {"signal": "BUY", "confidence": round(confidence, 2),
                    "reason": f"LSTM predicts upward sequence (conf: {confidence:.2f})"}
        elif predicted_class == 0 and confidence > 0.55:
            return {"signal": "SELL", "confidence": round(confidence, 2),
                    "reason": f"LSTM predicts downward sequence (conf: {confidence:.2f})"}
        else:
            return {"signal": "WAIT", "confidence": round(confidence, 2),
                    "reason": f"LSTM predicts flat or low confidence (conf: {confidence:.2f})"}
