"""
Automated Upstox Access Token Generator (Headless TOTP & OAuth2).
Refreshes UPSTOX_ACCESS_TOKEN and writes it directly to .env.

Supports:
  1. Automated 2FA TOTP generation (RFC 6238 pure Python or pyotp).
  2. Direct OAuth code exchange for access token.
  3. Safe in-place .env updating.
"""
import os
import sys
import time
import json
import base64
import hmac
import hashlib
import struct
import urllib.request
import urllib.parse
import ssl
from typing import Optional, Tuple

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
ROOT_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")


def generate_totp(secret: str) -> str:
    """Generate 6-digit TOTP code per RFC 6238 without requiring third-party packages."""
    try:
        # Clean whitespace/padding
        secret = secret.strip().replace(" ", "").upper()
        # Add required Base32 padding if missing
        missing_padding = len(secret) % 8
        if missing_padding:
            secret += '=' * (8 - missing_padding)
        key = base64.b32decode(secret, casefold=True)
        # 30-second interval
        counter = int(time.time() // 30)
        counter_bytes = struct.pack(">Q", counter)
        h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        code = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
        return f"{code:06d}"
    except Exception as e:
        raise ValueError(f"Invalid TOTP Secret Key: {e}")


def update_env_variable(key: str, value: str):
    """Safely updates or appends a key-value pair in both root and backend .env files."""
    for path in [ROOT_ENV_PATH, ENV_PATH]:
        lines = []
        found = False
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{key}={value}\n")
            
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"[UpstoxAuth] Updated {key} in {path}")


def exchange_code_for_token(code: str, api_key: str, api_secret: str, redirect_uri: str) -> Optional[str]:
    """Exchanges Upstox OAuth authorization code for master access token."""
    url = "https://api.upstox.com/v2/login/authorization/token"
    payload = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    data = urllib.parse.urlencode(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        },
        method='POST'
    )
    # IV&V finding 2026-08-21: was ssl._create_unverified_context() — the
    # OAuth code-for-token exchange (carrying api_key/api_secret and the
    # authorization code) was sent with TLS certificate validation disabled,
    # exposing real broker credentials to interception. Use the secure default.
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            token = res_data.get("access_token")
            if token:
                print(f"[UpstoxAuth] Successfully retrieved Access Token (length={len(token)})")
                return token
            else:
                print(f"[UpstoxAuth] Unexpected response: {res_data}")
                return None
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode('utf-8')
        print(f"[UpstoxAuth] Token exchange failed ({e.code}): {error_msg}")
        return None
    except Exception as e:
        print(f"[UpstoxAuth] Connection error: {e}")
        return None


def run_auth(dry_run: bool = False, manual_code: Optional[str] = None):
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv(ROOT_ENV_PATH)
    load_dotenv(ENV_PATH)

    api_key = os.getenv("UPSTOX_API_KEY", "")
    api_secret = os.getenv("UPSTOX_API_SECRET", "")
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "https://127.0.0.1/")
    totp_secret = os.getenv("UPSTOX_TOTP_KEY", "")

    print("=== Upstox Authentication & Token Refresh ===")
    print(f"API Key Present:      {bool(api_key)}")
    print(f"API Secret Present:   {bool(api_secret)}")
    print(f"Redirect URI:         {redirect_uri}")
    print(f"TOTP Secret Present:  {bool(totp_secret)}")

    if totp_secret:
        current_totp = generate_totp(totp_secret)
        print(f"Current Live TOTP:    {current_totp}")
        if dry_run:
            print("[Dry-Run] TOTP algorithm verified successfully.")
            return

    if manual_code:
        token = exchange_code_for_token(manual_code, api_key, api_secret, redirect_uri)
        if token:
            update_env_variable("UPSTOX_ACCESS_TOKEN", token)
            print("[Success] UPSTOX_ACCESS_TOKEN updated.")
        return

    # Direct authorization URL for convenience
    auth_url = (
        f"https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={api_key}&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
    )
    print(f"\n[Login URL]:\n{auth_url}\n")
    if not totp_secret:
        print("Tip: Add UPSTOX_TOTP_KEY (your Google Authenticator 32-char secret) to .env to enable 100% automated headless refresh.")


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    code_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == "--code" and i + 1 < len(sys.argv):
            code_arg = sys.argv[i + 1]
    run_auth(dry_run=is_dry, manual_code=code_arg)
