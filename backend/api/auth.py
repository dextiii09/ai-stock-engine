"""
Optional API-key authentication for mutating endpoints.

Design (per IV&V C1 fix):
  * An OPTIONAL API key can be required. It is enforced only when the
    APP_API_KEY environment variable is set. This lets the existing
    same-origin frontend keep working today while allowing full auth to be
    switched on (set APP_API_KEY, send `x-api-key` header) without a code change.

WARNING (corrected 2026-08-21 audit — this comment previously claimed the
server "binds to 127.0.0.1 by default," which is FALSE and gave a false
sense of security):
  * `backend/main.py` reads `APP_HOST` with a default of **"0.0.0.0"** (all
    interfaces) — not 127.0.0.1. Only the Windows dev launcher
    (start_trading_bot.bat) explicitly overrides to 127.0.0.1; that script
    is not used by the documented Ubuntu VPS production deployment.
  * If the process is started without APP_HOST=127.0.0.1 (or without a
    reverse proxy / firewall restricting inbound access) AND without
    APP_API_KEY set, every mutating endpoint on this server — including
    /risk/emergency-kill-switch, /bot/start, /bot/stop, /models/retrain-all —
    is reachable by anyone on the internet with zero authentication.
  * On the production VPS, either set APP_API_KEY (and have the frontend
    send it), or bind to 127.0.0.1 behind a reverse proxy that authenticates
    requests, or restrict inbound port 8080 at the firewall. Do not rely on
    this module alone for production access control.

To enable hard auth:
  1. Set APP_API_KEY=<random-secret> in the environment / .env.
  2. Have the frontend send it as the `x-api-key` request header.
"""
import os
import hmac

from fastapi import Header, HTTPException


def _configured_key() -> str:
    return os.getenv("APP_API_KEY", "").strip()


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    """FastAPI dependency. No-op when APP_API_KEY is unset; otherwise requires
    a constant-time-matching `x-api-key` header."""
    expected = _configured_key()
    if not expected:
        return  # auth disabled — rely on localhost bind
    # Constant-time comparison to avoid timing side-channels.
    if not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
