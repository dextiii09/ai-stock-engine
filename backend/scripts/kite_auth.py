"""
Zerodha Kite Connect Authentication Helper.
Generates login URL and exchanges request_token for daily access_token.
"""
import os
import json
import hashlib
from dotenv import load_dotenv

load_dotenv()

KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")

SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kite_session.json")


def get_login_url() -> str:
    """Returns the Zerodha Kite Connect login URL."""
    return f"https://kite.zerodha.com/connect/login?v=3&api_key={KITE_API_KEY}"


def generate_session(request_token: str) -> dict:
    """
    Exchanges request_token for access_token using Kite Connect REST API.
    Does not require third-party libraries (pure standard library HTTP request).
    """
    import urllib.request
    import urllib.parse
    
    # Compute SHA-256 checksum: api_key + request_token + api_secret
    raw_str = f"{KITE_API_KEY}{request_token}{KITE_API_SECRET}"
    checksum = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
    
    url = "https://api.kite.trade/session/token"
    payload = {
        "api_key": KITE_API_KEY,
        "request_token": request_token,
        "checksum": checksum,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-Kite-Version": "3",
            "User-Agent": "AI-Stock-Engine/3.0",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("status") == "success":
                session_data = resp_data.get("data", {})
                access_token = session_data.get("access_token")
                # Save session
                os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, indent=2)
                print(f"[KiteAuth] Access token generated successfully for user: {session_data.get('user_name', 'Zerodha User')}")
                return {"status": "success", "access_token": access_token, "data": session_data}
            else:
                return {"status": "error", "message": resp_data.get("message", "Unknown error")}
    except Exception as e:
        print(f"[KiteAuth] Session generation failed: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        req_tok = sys.argv[1].strip()
        res = generate_session(req_tok)
        print(json.dumps(res, indent=2))
    else:
        print("Login URL:")
        print(get_login_url())
