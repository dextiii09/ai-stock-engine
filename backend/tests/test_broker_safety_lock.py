"""
Regression test for a CRITICAL finding in the 2026-08-21 audit:

`ZerodhaBroker.buy()`/`sell()` route through `_place_order()`, which has an
explicit "Ironclad safety lock" — real orders are blocked unless
ENABLE_LIVE_REAL_MONEY_TRADING=true is set in the environment. `short()` and
`cover()` previously reimplemented order placement inline instead of calling
`_place_order()`, silently bypassing this exact safety check. If Zerodha were
ever selected as the active broker (mode="zerodha" in broker_config.json)
with valid credentials but the safety flag left at its default, a SHORT or
COVER signal would place a REAL order on the live exchange while BUY/SELL
stayed correctly blocked — a broker-wide safety mechanism with a hole in it.
`UpstoxBroker` and `IBKRBroker` were already correct (all 4 methods route
through their own `_place_order`); `ZerodhaBroker` now matches that pattern.

This test does not require the `kiteconnect` package to be installed — the
safety-lock check in `_place_order` runs before any kiteconnect usage, by
design, so blocking must work even when the broker never connected.
"""

import os

import pytest

from execution.broker_zerodha import ZerodhaBroker


@pytest.fixture(autouse=True)
def _ensure_safety_lock_default(monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_REAL_MONEY_TRADING", raising=False)


@pytest.mark.parametrize("method,args", [
    ("buy", ("RELIANCE.NS", 10, 2500.0)),
    ("sell", ("RELIANCE.NS", 10, 2500.0)),
    ("short", ("RELIANCE.NS", 10, 2500.0)),
    ("cover", ("RELIANCE.NS", 10, 2500.0)),
])
def test_all_four_order_methods_are_blocked_without_the_safety_flag(method, args):
    broker = ZerodhaBroker(api_key="x", api_secret="y", access_token="z")
    ok, msg, order_id = getattr(broker, method)(*args)

    assert ok is False, (
        f"ZerodhaBroker.{method}() placed an order despite "
        f"ENABLE_LIVE_REAL_MONEY_TRADING not being set to 'true' — the "
        f"safety lock does not cover this method."
    )
    assert "SAFETY LOCK" in msg
    assert order_id is None
