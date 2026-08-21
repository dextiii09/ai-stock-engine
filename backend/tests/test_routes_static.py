"""
Static (AST-based) regression checks on backend/api/routes.py.

routes.py has heavy import-time side effects (FastAPI app construction,
singleton trading engines for all 5 markets, Telegram bot init) so it is
never imported directly by the test suite (see test_critical_paths.py,
which tests the underlying engines instead). These checks parse the file's
AST instead, so they run with zero dependencies and no import side effects.
"""

import ast
import os

ROUTES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "api", "routes.py"
)


def _get_function(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found in routes.py")


def test_run_market_loop_has_no_undefined_market_name():
    """
    Regression test for a CRITICAL bug found in the 2026-08-21 audit:

    `_run_market_loop` (the shared trading loop body for the Stocks, Crypto,
    and Forex markets) referenced an undefined variable `market_name` in the
    BTC-USD MetaGate veto condition:

        if signal == "BUY" and market_name == "CRYPTO" and symbol.upper() == "BTC-USD":

    `market_name` was never defined anywhere in the codebase (only
    `market_label` is passed into the function). Because Python evaluates
    `and` left-to-right, this raised NameError on EVERY BUY signal in
    Stocks/Crypto/Forex — silently swallowed by the loop's outer
    `except Exception` per-symbol handler — meaning those three markets
    could never open a LONG or cover a SHORT. SELL signals were unaffected.

    This test guards against the identifier `market_name` (singular,
    undefined) ever reappearing inside `_run_market_loop` again. It does not
    import routes.py — it only parses the source, so it has no dependency
    on the heavy runtime environment.
    """
    with open(ROUTES_PATH, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=ROUTES_PATH)
    func = _get_function(tree, "_run_market_loop")

    bad_names = {
        node.id for node in ast.walk(func)
        if isinstance(node, ast.Name) and node.id == "market_name"
    }
    assert not bad_names, (
        "`_run_market_loop` references the undefined variable `market_name` "
        "again — this will raise NameError on every BUY signal in the "
        "Stocks/Crypto/Forex markets. Use the `market_label` parameter "
        "instead (compare case-insensitively, e.g. market_label.upper())."
    )

    # The correct replacement must actually be present.
    assert "market_label.upper() == \"CRYPTO\"" in ast.get_source_segment(source, func), (
        "Expected the BTC-USD MetaGate veto to gate on `market_label.upper() "
        "== \"CRYPTO\"` — the fix appears to have been reverted or rewritten."
    )


def test_indian_gemini_agent_weight_is_zeroed():
    """
    Regression test for a HIGH finding in the 2026-08-21 audit:

    `IndianMasterAgent` (backend/agents/master.py) appends `IndianGeminiAgent`
    (an LLM macro-commentary agent hitting NVIDIA/Gemini APIs live) to its
    committee. Like `SentimentAgent`, this agent has no point-in-time
    backtest — LLM calls can't be replayed over historical bars — which is
    the exact reason `SentimentAgent` and `CorrelationAgent` are explicitly
    zeroed (`agent_weights["News & Sentiment AI"] = 0.0`, etc.) before every
    live committee evaluation. `IndianGeminiAgent` was never added to that
    zero-list, and it isn't in the RL engine's tracked agent schema either
    (see `_GHOST_AGENTS` in analytics/rl_engine.py) — so
    `master.py`'s `agent_weights.get(agent.name, 1.0)` fallback gave it a
    permanent, un-learned, un-decaying full vote in every India-market
    decision. This guards against that zeroing line being lost again.
    """
    with open(ROUTES_PATH, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=ROUTES_PATH)
    func = _get_function(tree, "indian_trading_loop")
    func_src = ast.get_source_segment(source, func)
    assert '_live_weights_in["Indian Gemini AI"] = 0.0' in func_src, (
        "indian_trading_loop no longer zeroes the IndianGeminiAgent's RL "
        "weight — this un-backtested LLM agent will vote at full un-tuned "
        "strength (1.0) on every India-market trading decision again."
    )


def test_agent_weights_endpoints_mask_ghost_agents():
    """
    Regression test for a LOW/UI-honesty finding in the 2026-08-21 audit
    (Finding #13, second half):

    The live trading loops (US/India/Stocks/Crypto/Forex) all force
    "News & Sentiment AI" and "Correlation Agent" (and, for India,
    "Indian Gemini AI") to weight 0.0 before every real decision — neither
    can be point-in-time backtested. But the 5 `/analytics/agent-weights`
    display endpoints previously returned the RL engine's raw, un-masked
    learned weights, misleadingly implying those agents still vote when the
    dashboard is viewed. This guards against that masking being dropped from
    any of the 5 endpoints again.
    """
    with open(ROUTES_PATH, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=ROUTES_PATH)

    endpoints = [
        "get_agent_weights", "get_agent_weights_in", "get_agent_weights_st",
        "get_agent_weights_cx", "get_agent_weights_fx",
    ]
    for name in endpoints:
        func = _get_function(tree, name)
        func_src = ast.get_source_segment(source, func)
        assert '"News & Sentiment AI"] = 0.0' in func_src, (
            f"{name} no longer masks the Sentiment agent's display weight to 0.0."
        )
        assert '"Correlation Agent"]   = 0.0' in func_src or '"Correlation Agent"] = 0.0' in func_src, (
            f"{name} no longer masks the Correlation agent's display weight to 0.0."
        )

    india_func_src = ast.get_source_segment(source, _get_function(tree, "get_agent_weights_in"))
    assert '"Indian Gemini AI"]    = 0.0' in india_func_src or '"Indian Gemini AI"] = 0.0' in india_func_src, (
        "get_agent_weights_in no longer masks the Indian Gemini agent's display weight to 0.0."
    )
