"""
conftest.py — stub out heavy runtime dependencies so unit tests can import
SmartExecutionEngine without a full Python environment.

Only modules that cannot be installed in a minimal test environment
(yfinance, hmmlearn, pandas, ta, etc.) are stubbed.
"""

import os
import sys
import tempfile
import types
from unittest.mock import MagicMock

# IV&V finding 2026-08-21 (audit Finding #8): TradePostMortemEngine wrote
# every closed-trade post-mortem to the real, git-tracked
# backend/data/trade_journal.json — any test that exercises force_close()/
# execute_trade()'s SELL/COVER branches (which fire this asynchronously in a
# background thread) polluted real production data on every test run,
# requiring a manual `git checkout` after every single suite run this
# session. Point it at an isolated per-session temp file instead; production
# is unaffected since TRADE_JOURNAL_PATH is unset there.
os.environ["TRADE_JOURNAL_PATH"] = os.path.join(
    tempfile.gettempdir(), "ai_stock_test_trade_journal.json"
)

# IV&V finding 2026-08-21: app code logs emoji characters (e.g. the
# GlobalRiskAggregator circuit-breaker halt message). On a plain Windows
# console, sys.stdout defaults to a legacy codepage (cp1252) that can't
# encode them, which raises UnicodeEncodeError deep inside pytest's own
# capture layer and corrupts it — the whole test run then dies at teardown
# with an unrelated-looking `ValueError: I/O operation on closed file`,
# silently hiding whether the tests actually passed. Mirrors the same fix
# applied to backend/main.py for the production process.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _stub(name: str, **attrs):
    """Create a lightweight module stub and register it (and its sub-paths)."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Only stub if not already available
_HEAVY = [
    "yfinance",
    "hmmlearn", "hmmlearn.hmm",
    "ta", "ta.trend", "ta.momentum", "ta.volatility",
    "sklearn", "sklearn.ensemble", "sklearn.linear_model",
    "sklearn.preprocessing", "sklearn.feature_selection",
    "boruta", "scipy", "scipy.stats",
    "vaderSentiment", "vaderSentiment.vaderSentiment",
    "feedparser",
    "dotenv",
    "numba",
]

for _pkg in _HEAVY:
    if _pkg not in sys.modules:
        _stub(_pkg)

# vaderSentiment needs SentimentIntensityAnalyzer
if "vaderSentiment.vaderSentiment" in sys.modules:
    _sia = MagicMock()
    _sia.polarity_scores.return_value = {"compound": 0.0}
    sys.modules["vaderSentiment.vaderSentiment"].SentimentIntensityAnalyzer = lambda: _sia

# dotenv needs load_dotenv
if "dotenv" in sys.modules:
    sys.modules["dotenv"].load_dotenv = lambda *a, **kw: None

# GaussianHMM stub
class _GaussianHMM:
    def __init__(self, *a, **kw): pass
    def fit(self, X): return self
    def predict(self, X): return [0] * len(X)
    means_ = None
    transmat_ = None

if "hmmlearn.hmm" in sys.modules:
    sys.modules["hmmlearn.hmm"].GaussianHMM = _GaussianHMM

# Stub broker_factory (avoids more transitive imports)
class _PaperBroker:
    name    = "PaperBroker"
    is_live = False
    def buy(self, *a, **kw): return True, "ok", "order_1"
    def sell(self, *a, **kw): return True, "ok", "order_2"
    def short(self, *a, **kw): return True, "ok", "order_3"
    def cover(self, *a, **kw): return True, "ok", "order_4"
    def normalize_quantity(self, symbol, qty): return float(qty)

_paper_broker_inst = _PaperBroker()
_bf = _stub("execution.broker_factory")
_bf.get_current_mode = lambda: "paper"
_bf.save_config = lambda *a, **kw: None
_bf.get_broker = lambda *a, **kw: _paper_broker_inst  # module-level function
_bf.BrokerFactory = MagicMock()
_bf.BrokerFactory.get_broker.return_value = _paper_broker_inst

# Stub database modules
_db = _stub("database.database")
_db.AsyncSessionLocal = MagicMock()
_db.Base = MagicMock()
_db.engine = MagicMock()

_dm = _stub("database.models")
_dm.Log = MagicMock()
_dm.Order = MagicMock()
_dm.Portfolio = MagicMock()
_dm.RLWeight = MagicMock()
_dm.SYSTEM_USER_ID = None
