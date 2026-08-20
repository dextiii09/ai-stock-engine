#!/usr/bin/env python3
"""
AI Stock Bot - Log Monitor
Watches logs/server.log for errors and polls the API for bot status.
Run in a separate terminal: python backend\log_monitor.py
"""
import os
import sys
import time
import requests
from datetime import datetime
from collections import deque

BASE_URL      = "http://localhost:8080/api/v1"
LOG_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "server.log")
REFRESH_SECS  = 30
MAX_ISSUES    = 25

# ── Error / warning patterns to watch for ──────────────────────────────────────
# Use bracketed level tags like [ERROR] to avoid false-positives on logger
# names (e.g. "uvicorn.error" in INFO lines) or debug words ("trading_loop").
_ERROR_PATS = [
    "[ERROR]", "[CRITICAL]", "Exception", "Traceback",
    "database is locked", "MemoryError", "PermissionError",
    "Bot stopped", "OMP: Error",
]
_WARN_PATS  = [
    "[WARNING]", "Too Many Requests", "possibly delisted",
    "Failed to write", "HyperOpt",
]
# ──────────────────────────────────────────────────────────────────────────────

_file_pos   = 0
_issues     = deque(maxlen=MAX_ISSUES)  # (icon, text) tuples


def _api(path: str):
    try:
        r = requests.get(f"{BASE_URL}/{path}", timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _scan_log() -> list:
    """Read new lines from server.log since last call. Returns list of (icon, text)."""
    global _file_pos
    found = []
    if not os.path.exists(LOG_FILE):
        return found
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            f.seek(_file_pos)
            lines = f.readlines()
            _file_pos = f.tell()

        for raw in lines:
            line = raw.rstrip()
            if not line:
                continue
            # Case-sensitive match so "[ERROR]" doesn't hit "uvicorn.error"
            if any(p in line for p in _ERROR_PATS):
                found.append(("ERR", line))
            elif any(p in line for p in _WARN_PATS):
                found.append(("WRN", line))
    except Exception as exc:
        found.append(("ERR", f"[Monitor] Could not read log file: {exc}"))
    return found


def _bar(ok: bool) -> str:
    return "ONLINE  " if ok else "OFFLINE "


def _render():
    os.system("cls" if os.name == "nt" else "clear")
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

    print("╔══════════════════════════════════════════════════╗")
    print(f"║   AI STOCK BOT MONITOR  │  {now}  ║")
    print("╚══════════════════════════════════════════════════╝")

    # ── Server health ──
    health = _api("health")
    server_ok = health is not None
    print(f"\n  Server   : {'✅ ONLINE' if server_ok else '❌ OFFLINE — server is not running!'}")

    if not server_ok:
        print(f"\n  Retrying in {REFRESH_SECS}s... (Ctrl+C to stop)")
        return

    # ── Bot status ──
    us  = _api("bot/status")        or {}
    ind = _api("indian/bot/status") or {}
    us_run  = us.get("is_running",  False)
    ind_run = ind.get("is_running", False)

    print(f"  US Bot   : {'✅ RUNNING' if us_run  else '🔴 STOPPED'}")
    print(f"  India Bot: {'✅ RUNNING' if ind_run else '🔴 STOPPED'}")

    # ── Scan log file ──
    new = _scan_log()
    for item in new:
        _issues.append(item)

    # ── Show issues ──
    errors  = [(i, m) for i, m in _issues if i == "ERR"]
    warns   = [(i, m) for i, m in _issues if i == "WRN"]

    print(f"\n─── Recent Issues ({len(errors)} errors, {len(warns)} warnings) ───")
    if not _issues:
        print("  ✅ No issues detected yet.")
    else:
        # Show last 12 items, errors first
        shown = sorted(list(_issues), key=lambda x: 0 if x[0] == "ERR" else 1)[-12:]
        for icon, msg in shown:
            prefix = "❌" if icon == "ERR" else "⚠️ "
            # Trim very long lines
            display = msg[:100] + ("…" if len(msg) > 100 else "")
            print(f"  {prefix} {display}")

    # ── Log file info ──
    log_size = 0
    if os.path.exists(LOG_FILE):
        log_size = os.path.getsize(LOG_FILE) / 1024
    print(f"\n  Log file : {LOG_FILE}")
    print(f"  Log size : {log_size:.1f} KB  │  position: {_file_pos} bytes")
    print(f"\n  Refreshing every {REFRESH_SECS}s — Ctrl+C to stop")


def main():
    print("=" * 52)
    print("  AI Stock Bot Log Monitor starting...")
    print(f"  Watching: {LOG_FILE}")
    print(f"  API     : {BASE_URL}")
    print("=" * 52)

    if not os.path.exists(LOG_FILE):
        print(f"\n  ⚠️  Log file not found yet.")
        print(f"  Make sure you started the bot with start_trading_bot.bat")
        print(f"  (the new version captures output to the log file)")

    time.sleep(2)

    while True:
        try:
            _render()
        except KeyboardInterrupt:
            print("\n\n  Monitor stopped.")
            sys.exit(0)
        except Exception as exc:
            print(f"\n  Monitor error: {exc}")
        time.sleep(REFRESH_SECS)


if __name__ == "__main__":
    main()
