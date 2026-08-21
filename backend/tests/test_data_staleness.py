"""
Regression tests for a HIGH finding in the 2026-08-21 audit:

`YFinanceDataProvider.get_historical_ohlcv()` silently serves cached data up
to `_STALE_FALLBACK_TTL` (10 minutes) old when live Yahoo Finance fetches
fail 3x in a row — but the returned DataFrame was previously indistinguishable
from a fresh fetch to every caller. `data/ingestion.py` labeled every tick
"Yahoo Finance (real)" regardless, so the committee/risk/sizing layers could
make live trading decisions on a price up to 10 minutes stale while believing
it was live — violating the system's own stated design rule ("if data is
unavailable, the engine pauses safely").

The fix tags the returned DataFrame's `.attrs` with `is_stale` and
`data_age_seconds`, which `ingestion.py` now reads to build an honest
`data_source` string and `is_stale_data`/`data_age_seconds` tick fields.
"""

import sys
import time
import types
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _make_ohlcv_df(n=20):
    idx = pd.date_range("2026-08-21", periods=n, freq="1min")
    return pd.DataFrame({
        "Open":   [100.0] * n,
        "High":   [101.0] * n,
        "Low":    [99.0] * n,
        "Close":  [100.5] * n,
        "Volume": [1000] * n,
    }, index=idx)


@pytest.fixture
def provider(monkeypatch):
    # Import fresh so each test gets an isolated instance / mocked yfinance.
    if "data.provider" in sys.modules:
        del sys.modules["data.provider"]

    fake_yf = types.ModuleType("yfinance")
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    import importlib
    provider_mod = importlib.import_module("data.provider")
    return provider_mod


def test_fresh_fetch_is_tagged_not_stale(provider, monkeypatch):
    df = _make_ohlcv_df()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    monkeypatch.setattr(provider.yf, "Ticker", lambda symbol: mock_ticker, raising=False)

    p = provider.YFinanceDataProvider()
    result = p.get_historical_ohlcv("MGC=F", period="2d", interval="1m")

    assert result.attrs.get("is_stale") is False
    assert result.attrs.get("data_age_seconds") == 0.0


def test_stale_fallback_is_honestly_tagged(provider, monkeypatch):
    df = _make_ohlcv_df()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    monkeypatch.setattr(provider.yf, "Ticker", lambda symbol: mock_ticker, raising=False)
    monkeypatch.setattr(provider.time, "sleep", lambda *_: None)   # skip real backoff delay

    p = provider.YFinanceDataProvider()
    # Prime the cache with a "10 minutes ago" fetch.
    p._cache[("MGC=F", "2d", "1m")] = (df, time.time() - 120.0)

    # Now make every live attempt fail.
    failing_ticker = MagicMock()
    failing_ticker.history.side_effect = RuntimeError("network down")
    monkeypatch.setattr(provider.yf, "Ticker", lambda symbol: failing_ticker, raising=False)

    result = p.get_historical_ohlcv("MGC=F", period="2d", interval="1m")

    assert result.attrs.get("is_stale") is True
    age = result.attrs.get("data_age_seconds")
    assert age is not None and 110.0 <= age <= 130.0


def test_expired_stale_cache_raises_instead_of_silently_serving_ancient_data(provider, monkeypatch):
    df = _make_ohlcv_df()
    p = provider.YFinanceDataProvider()
    # Cache is older than _STALE_FALLBACK_TTL (600s).
    p._cache[("MGC=F", "2d", "1m")] = (df, time.time() - 900.0)

    failing_ticker = MagicMock()
    failing_ticker.history.side_effect = RuntimeError("network down")
    monkeypatch.setattr(provider.yf, "Ticker", lambda symbol: failing_ticker, raising=False)
    monkeypatch.setattr(provider.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError):
        p.get_historical_ohlcv("MGC=F", period="2d", interval="1m")
