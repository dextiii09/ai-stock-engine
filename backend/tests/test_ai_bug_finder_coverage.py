"""
Regression test for a MEDIUM finding in the 2026-08-21 audit:

`AIBugFinder`'s runtime checks (`_rt_portfolio_balance`, `_rt_rl_weights`)
previously only polled the US market (and, for balance, India) —
Stocks/Crypto/Forex had zero runtime monitoring from this tool, mirroring
the exact 3-market blind spot the market_name bug (audit Finding #1) had.
A negative balance or NaN/Inf RL weight in those 3 markets would have gone
completely undetected by the tool that's supposed to catch exactly that.

This test verifies both checks now poll all 5 markets.
"""

from unittest.mock import MagicMock, patch

from ai_bug_finder import AIBugFinder


def _mock_response(json_body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def test_rt_portfolio_balance_polls_all_five_markets():
    finder = AIBugFinder()
    with patch("requests.get", return_value=_mock_response({"balance": 1000.0})) as mock_get:
        finder._rt_portfolio_balance(__import__("requests"))

    called_urls = [call.args[0] for call in mock_get.call_args_list]
    assert len(called_urls) == 5, f"Expected 5 market polls, got {len(called_urls)}: {called_urls}"
    for prefix in ("/portfolio/holdings", "/indian/portfolio/holdings",
                   "/stocks/portfolio/holdings", "/crypto/portfolio/holdings",
                   "/forex/portfolio/holdings"):
        assert any(url.endswith(prefix) for url in called_urls), (
            f"Missing runtime balance check for endpoint ending in {prefix!r}: {called_urls}"
        )


def test_rt_rl_weights_polls_all_five_markets():
    finder = AIBugFinder()
    with patch("requests.get", return_value=_mock_response({"weights": {}})) as mock_get:
        finder._rt_rl_weights(__import__("requests"))

    called_urls = [call.args[0] for call in mock_get.call_args_list]
    assert len(called_urls) == 5, f"Expected 5 market polls, got {len(called_urls)}: {called_urls}"
    for prefix in ("/analytics/rl-stats", "/indian/analytics/rl-stats",
                   "/stocks/analytics/rl-stats", "/crypto/analytics/rl-stats",
                   "/forex/analytics/rl-stats"):
        assert any(url.endswith(prefix) for url in called_urls), (
            f"Missing runtime RL-weight check for endpoint ending in {prefix!r}: {called_urls}"
        )


def test_rt_portfolio_balance_flags_negative_balance_in_a_non_us_market():
    """The whole point of the fix: a negative Crypto balance must be caught."""
    finder = AIBugFinder()

    def fake_get(url, timeout=5, proxies=None):
        if "/crypto/" in url:
            return _mock_response({"balance": -500.0})
        return _mock_response({"balance": 1000.0})

    with patch("requests.get", side_effect=fake_get):
        finder._rt_portfolio_balance(__import__("requests"))

    findings = finder.get_findings()
    crypto_findings = [f for f in findings if "Crypto" in f["location"]]
    assert crypto_findings, "Negative Crypto balance was not flagged as a finding."
    assert crypto_findings[0]["severity"] == "CRITICAL"
