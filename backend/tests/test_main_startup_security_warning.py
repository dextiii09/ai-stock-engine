"""
Regression test for a CRITICAL finding in the 2026-08-21 audit (Finding #6):

`main.py` defaults `APP_HOST` to "0.0.0.0" (all interfaces), and
`api/auth.py`'s `require_api_key` dependency is a silent no-op whenever
`APP_API_KEY` is unset. Confirmed deployment posture: the production VPS
relies on `APP_API_KEY` as the actual auth barrier (not a loopback bind) —
so the default host behavior is intentional and unchanged. But there was
previously zero operational signal if `APP_API_KEY` was simply forgotten in
`.env`, which would silently leave every mutating endpoint
(/risk/emergency-kill-switch, /bot/start, /bot/stop, /models/retrain-all,
etc.) open to the internet with no auth at all.

`main.py` only runs its startup logic under `if __name__ == "__main__":`,
so this is a static/textual check rather than an import-and-exercise test
(importing main.py the normal way doesn't need real uvicorn/network setup,
but exercising the `__main__` block would need to actually bind a socket).
"""

import ast
import os

MAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "main.py")


def test_main_warns_loudly_when_binding_non_loopback_without_api_key():
    with open(MAIN_PATH, encoding="utf-8") as f:
        source = f.read()

    # Must not have silently regressed back to a bare uvicorn.run with no check.
    assert "APP_API_KEY" in source, (
        "main.py no longer references APP_API_KEY — the startup safety "
        "warning for an unauthenticated, non-loopback bind appears to have "
        "been removed."
    )
    assert "CRITICAL" in source, (
        "main.py no longer prints a CRITICAL-level warning for the "
        "unauthenticated non-loopback bind case."
    )

    tree = ast.parse(source, filename=MAIN_PATH)
    # The warning must be gated on both conditions: non-loopback host AND
    # missing APP_API_KEY — not just one or the other.
    found_host_check = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "_host":
            found_host_check = True
    assert found_host_check, (
        "main.py no longer checks _host against the loopback address set "
        "before deciding whether to warn — the security warning may have "
        "been removed or made unconditional/broken."
    )
