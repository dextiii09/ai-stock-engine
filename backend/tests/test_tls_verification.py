"""
Regression tests for a CRITICAL security finding in the 2026-08-21 audit:

Four files disabled TLS certificate validation entirely via
`ssl._create_unverified_context()` — including `broker_upstox.py`'s real
order-placement HTTP call (carrying the Bearer access token and live order
details) and `auto_upstox_login.py`'s OAuth code-for-token exchange (carrying
real broker api_key/api_secret). Both were vulnerable to interception or
tampering by anyone on the network path (MITM). `telegram_bot.py` and
`notifier.py` had the same issue for every Telegram/Discord API call.

Confirmed live in this session that `ssl.create_default_context()` (the
secure fix) successfully completes real TLS handshakes against
api.telegram.org, api.upstox.com, and api.kite.trade in this environment —
so the fix does not trade security for broken connectivity here.

These tests assert the SSL contexts these modules construct actually
enforce certificate validation (`verify_mode=CERT_REQUIRED`,
`check_hostname=True` — `create_default_context()`'s properties) rather than
`_create_unverified_context()`'s (`CERT_NONE`, `check_hostname=False`).
"""

import ssl


def _assert_context_verifies(ctx: ssl.SSLContext, label: str):
    assert ctx.verify_mode == ssl.CERT_REQUIRED, (
        f"{label}: SSL context does not require certificate verification "
        f"(verify_mode={ctx.verify_mode!r}) — TLS validation is disabled."
    )
    assert ctx.check_hostname is True, (
        f"{label}: SSL context does not check hostname — vulnerable to MITM "
        f"even if verify_mode were correct."
    )


def test_notifier_ssl_context_verifies_certificates():
    from utils.notifier import Notifier
    n = Notifier()
    _assert_context_verifies(n.ssl_context, "utils.notifier.Notifier")


def test_telegram_bot_ssl_context_verifies_certificates():
    import utils.telegram_bot as tb
    _assert_context_verifies(tb._ssl_ctx, "utils.telegram_bot")


def test_upstox_broker_ssl_context_verifies_certificates():
    from execution.broker_upstox import UpstoxBroker
    broker = UpstoxBroker(access_token="")  # no real token needed to construct
    _assert_context_verifies(broker.ssl_context, "execution.broker_upstox.UpstoxBroker")


def test_auto_upstox_login_uses_verified_context():
    """
    Static check: `auto_upstox_login.py`'s exchange_code_for_token() builds
    its SSL context inline (not stored on an object), so this asserts the
    source no longer contains the unverified-context call.
    """
    import ast
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "auto_upstox_login.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)

    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("create_default_context", "_create_unverified_context")
    }
    assert "_create_unverified_context" not in calls, (
        "auto_upstox_login.py still calls ssl._create_unverified_context() "
        "for the OAuth token exchange — real broker credentials are exposed "
        "to interception."
    )
    assert "create_default_context" in calls, (
        "auto_upstox_login.py no longer calls ssl.create_default_context() "
        "for the OAuth token exchange."
    )
