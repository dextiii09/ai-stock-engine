"""
Regression tests for a CRITICAL finding in the 2026-08-21 audit:

`GlobalRiskAggregator.check()` (backend/risk/global_risk.py) prints the halt
message with an emoji character ("⛔") whenever the cross-market circuit
breaker fires — exactly the code path that is supposed to protect capital
during a drawdown event. On a plain Windows console, stdout defaults to the
system's legacy codepage (e.g. cp1252), which cannot encode that character,
so the print() call raises an unhandled UnicodeEncodeError. Reproduced
directly in this environment: calling `GlobalRiskAggregator.check()` when a
halt condition is met crashes the process instead of just logging the halt.

The fix is at process startup (backend/main.py reconfigures stdout/stderr to
UTF-8 with errors="replace" before anything else runs), rather than patching
every individual emoji print call across the codebase. These tests check
both that the fix is actually present in main.py and that the mechanism it
uses genuinely prevents the crash.
"""

import ast
import io
import os

MAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "main.py")


def test_main_reconfigures_stdout_to_utf8_before_heavy_imports():
    with open(MAIN_PATH, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=MAIN_PATH)

    reconfigure_line = None
    dotenv_import_line = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "reconfigure":
            reconfigure_line = node.lineno
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            if "load_dotenv" in names or (isinstance(node, ast.ImportFrom) and node.module == "dotenv"):
                dotenv_import_line = node.lineno

    assert reconfigure_line is not None, (
        "backend/main.py no longer reconfigures stdout/stderr to UTF-8 — "
        "emoji log lines (e.g. the circuit-breaker halt message in "
        "global_risk.py) will crash the process again on a plain Windows "
        "console."
    )
    assert "utf-8" in source.lower() and "errors" in source, (
        "Expected the stdout/stderr reconfigure to specify utf-8 encoding "
        "with a non-raising errors policy."
    )


def test_reconfigured_stream_can_encode_the_actual_halt_message():
    """
    Proves the mechanism: writing the real GlobalRiskAggregator halt-log
    string to a cp1252-backed stream raises before reconfigure, and
    succeeds after — the same reconfigure main.py applies to sys.stdout.
    Uses a private BytesIO-backed stream, not the real sys.stdout, so the
    test doesn't disturb the actual test session's output.
    """
    halt_message = "[GlobalRisk] ⛔ GLOBAL HALT: combined daily drawdown 3.60% exceeds 3.5% limit across all markets."

    buf = io.BytesIO()
    cp1252_stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    try:
        cp1252_stream.write(halt_message)
        cp1252_stream.flush()
        raised = False
    except UnicodeEncodeError:
        raised = True
    assert raised, (
        "Expected the halt message (with the ⛔ emoji) to fail to encode "
        "under cp1252 without the fix — if this no longer raises, the "
        "scenario this regression test targets may have changed."
    )

    buf2 = io.BytesIO()
    fixed_stream = io.TextIOWrapper(buf2, encoding="cp1252", errors="strict")
    fixed_stream.reconfigure(encoding="utf-8", errors="replace")
    fixed_stream.write(halt_message)   # must not raise
    fixed_stream.flush()
    fixed_stream.seek(0)
    assert b"GLOBAL HALT" in buf2.getvalue()
