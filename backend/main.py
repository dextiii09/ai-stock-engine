import os as _os
import socket
import sys

# IV&V finding 2026-08-21: extensive logging across the codebase (routes.py,
# global_risk.py's circuit-breaker halt, execution engines, etc.) uses emoji
# characters (e.g. "⛔", "🚨"). On Windows, stdout/stderr default to the
# console's legacy codepage (cp1252 etc.), not UTF-8 — any such print() then
# raises an unhandled UnicodeEncodeError. Reproduced directly: calling
# GlobalRiskAggregator.check() when a drawdown halt fires crashes with
# UnicodeEncodeError on a plain Windows console — i.e. the circuit breaker
# that is supposed to protect capital during a drawdown event could itself
# crash the whole engine process at exactly the worst moment. Fix it once,
# process-wide, instead of patching every emoji print call site.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from api.server import app

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

if __name__ == "__main__":
    PORT = int(_os.getenv("PORT", "8080"))
    
    if is_port_in_use(PORT):
        print(f"\n[WARNING] Port {PORT} is already in use!")
        print("It looks like the server is already running (either manually or in the background).")
        print("Skipping duplicate server startup to prevent conflicts.\n")
        sys.exit(0)
        
    _host = _os.getenv("APP_HOST", "0.0.0.0")

    # IV&V finding 2026-08-21 (audit Finding #6): APP_HOST defaults to
    # 0.0.0.0 (all interfaces), and require_api_key() in api/auth.py is a
    # silent no-op whenever APP_API_KEY is unset. Confirmed deployment
    # posture: production VPS relies on APP_API_KEY as the actual auth
    # barrier (not a loopback bind), so this does not change that default —
    # but there was previously zero operational signal if APP_API_KEY was
    # simply forgotten in .env, which would silently leave every mutating
    # endpoint (/risk/emergency-kill-switch, /bot/start, /bot/stop,
    # /models/retrain-all, etc.) open to the internet with no auth at all.
    if _host not in ("127.0.0.1", "localhost", "::1") and not _os.getenv("APP_API_KEY", "").strip():
        _warning = (
            "\n" + "!" * 78 +
            "\n! CRITICAL: server is binding to " + _host + " (not loopback) and\n"
            "! APP_API_KEY is NOT set. Every mutating endpoint on this API —\n"
            "! including /risk/emergency-kill-switch, /bot/start, /bot/stop, and\n"
            "! /models/retrain-all — is reachable by ANYONE on the network with\n"
            "! ZERO authentication.\n"
            "!\n"
            "! Fix: set APP_API_KEY=<random-secret> in .env (and have the frontend\n"
            "! send it as the x-api-key header), OR set APP_HOST=127.0.0.1 and put\n"
            "! a firewall/reverse-proxy in front of this process.\n"
            + "!" * 78 + "\n"
        )
        print(_warning, file=sys.stderr)

    uvicorn.run("api.server:app", host=_host, port=PORT, reload=False)


