"""
Optional API-key authentication for mutating endpoints.

Design (per IV&V C1 fix):
  * The server binds to 127.0.0.1 by default (see start_trading_bot.bat), which
    removes the LAN/internet attack surface entirely.
  * On top of that, an OPTIONAL API key can be required. It is enforced only
    when the APP_API_KEY environment variable is set. This lets the existing
    same-origin frontend keep working today while allowing full auth to be
    switched on (set APP_API_KEY, send `x-api-key` header) without a code change.

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
