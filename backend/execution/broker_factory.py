"""
Broker factory — returns the correct broker based on settings.

Settings are read from data/broker_config.json:
  {
    "mode":   "paper" | "zerodha" | "ibkr",
    "market": "US"    | "INDIA"
  }

The file is created on first run with mode=paper (safe default).
"""

import os
import json
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "broker_config.json")

_DEFAULT_CONFIG = {"mode": "paper", "market": "US"}


def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def save_config(mode: str, market: str = "US") -> None:
    cfg = {"mode": mode, "market": market}
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)
    print(f"[BrokerFactory] Config saved: mode={mode}, market={market}")


def get_broker(market: str = "US", override_mode: Optional[str] = None):
    """
    Returns a BrokerBase instance for the given market.

    Args:
        market:        'US' or 'INDIA'
        override_mode: if provided, ignores config and uses this mode
    """
    cfg  = _load_config()
    mode = override_mode or cfg.get("mode", "paper")

    if mode == "paper":
        from .broker_paper import PaperBroker
        return PaperBroker()

    if mode == "zerodha":
        if market != "INDIA":
            print("[BrokerFactory] Zerodha is India-only. Falling back to paper for US market.")
            from .broker_paper import PaperBroker
            return PaperBroker()
        from .broker_zerodha import ZerodhaBroker
        return ZerodhaBroker()

    if mode == "ibkr":
        from .broker_ibkr import IBKRBroker
        return IBKRBroker()

    if mode == "upstox":
        if market != "INDIA":
            print("[BrokerFactory] Upstox is India-only. Falling back to paper for US market.")
            from .broker_paper import PaperBroker
            return PaperBroker()
        from .broker_upstox import UpstoxBroker
        return UpstoxBroker()

    # Unknown mode — fallback
    print(f"[BrokerFactory] Unknown mode '{mode}'. Falling back to paper.")
    from .broker_paper import PaperBroker
    return PaperBroker()


def get_current_mode() -> str:
    return _load_config().get("mode", "paper")
