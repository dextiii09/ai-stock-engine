# ── Thread-count caps — MUST be set before numpy/sklearn are imported ──────────
# Without these, each asyncio.to_thread worker spawns N OMP threads (one per CPU
# core), causing exponential thread growth that eventually hits Windows limit 1450.
import os as _os
_os.environ.setdefault("OMP_NUM_THREADS",         "1")
_os.environ.setdefault("OPENBLAS_NUM_THREADS",    "1")
_os.environ.setdefault("MKL_NUM_THREADS",         "1")
_os.environ.setdefault("NUMEXPR_NUM_THREADS",     "1")
_os.environ.setdefault("VECLIB_MAXIMUM_THREADS",  "1")
# ────────────────────────────────────────────────────────────────────────────────

import logging
from logging.handlers import RotatingFileHandler as _RotatingFileHandler

# ── FIX 2026-08-03: global socket timeout for blocking (thread) I/O ─────────────
# yfinance/requests calls inside asyncio.to_thread workers have no timeout; a
# hung read froze the INDIA engine loop for ~14h. Loop-level wait_for guards
# cover the tick fetches, but MTF-confluence / MetaGate / scanner fetches are
# also in-loop awaits. This is the blanket guard: any blocking socket without
# an explicit timeout dies after 30s instead of hanging forever. Asyncio's own
# sockets are non-blocking, so uvicorn / SSE streams are NOT affected.
import socket as _socket
_socket.setdefaulttimeout(30)
# ────────────────────────────────────────────────────────────────────────────────

# ── File logging — captures all exceptions + uvicorn events to logs/server.log ──
_log_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "logs")
_os.makedirs(_log_dir, exist_ok=True)
_file_handler = _RotatingFileHandler(
    _os.path.join(_log_dir, "server.log"),
    maxBytes=5 * 1024 * 1024,   # 5 MB per file
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
# Add handler to leaf loggers only — NOT to the parent "uvicorn" logger.
# "uvicorn.error" propagates up to "uvicorn" by default, so adding the handler
# to both causes every line to be written twice to the file.
for _ln in ("uvicorn.error", "uvicorn.access", "fastapi"):
    _lg = logging.getLogger(_ln)
    _lg.addHandler(_file_handler)
    if _lg.level == logging.NOTSET:
        _lg.setLevel(logging.DEBUG)
# ────────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .routes import (
    router, auto_resume_bots,
    execution_engine, execution_engine_in,
    execution_engine_st, execution_engine_cx, execution_engine_fx,
)

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cap the asyncio default thread pool so asyncio.to_thread can't create
    # unbounded threads when many symbols are processed simultaneously.
    import asyncio
    import concurrent.futures
    loop = asyncio.get_event_loop()
    # 12 workers: 5 markets × asyncio.to_thread(fetch_all_*_ticks) + model update loops
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=12))

    # Windows ProactorEventLoop noise: when an SSE/HTTP client (e.g. the dashboard
    # polling /bot/stream) disconnects mid-response, asyncio raises a harmless
    # ConnectionResetError (WinError 10054) from
    # _ProactorBasePipeTransport._call_connection_lost. Swallow ONLY that case so
    # it stops flooding the log and masking genuine errors; everything else still
    # goes to the default handler.
    _prev_exc_handler = loop.get_exception_handler()

    def _quiet_connection_reset(_loop, context):
        if isinstance(context.get("exception"), ConnectionResetError):
            return
        if _prev_exc_handler is not None:
            _prev_exc_handler(_loop, context)
        else:
            _loop.default_exception_handler(context)

    loop.set_exception_handler(_quiet_connection_reset)

    # Startup: launch background schedulers & Telegram Bot controller
    from analytics.hyperopt_loop import start_scheduler
    start_scheduler()   # re-optimizes hyperparams every 30 days
    from ai_bug_finder import start_bug_finder
    start_bug_finder()  # continuous bug scanner (file watcher + runtime monitor)
    from utils.telegram_bot import telegram_bot
    await telegram_bot.start()  # two-way interactive Telegram Bot listener
    await auto_resume_bots()  # restart bots if they were running before laptop sleep
    logger.info("[Server] All schedulers started. AI Bug Finder & Telegram Bot active.")
    yield
    # Graceful shutdown: flush state to disk before process exits
    logger.info("[Server] Shutdown signal received. Saving all market states...")
    await telegram_bot.stop()
    for label, eng in [
        ("US",     execution_engine),
        ("Indian", execution_engine_in),
        ("Stocks", execution_engine_st),
        ("Crypto", execution_engine_cx),
        ("Forex",  execution_engine_fx),
    ]:
        try:
            eng.save_portfolio_state()
            logger.info(f"[Server] {label} engine state saved.")
        except Exception as e:
            logger.error(f"[Server] Failed to save {label} engine state: {e}")
    logger.info("[Server] Shutdown complete.")



app = FastAPI(
    title="AI Stock Engine API (V3 Architecture)",
    version="3.0.0",
    lifespan=lifespan,
)

# Configure CORS for the React frontend (supports localhost, VPS IP, and custom origins).
_default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [o.strip() for o in _os.getenv("APP_CORS_ORIGINS", _default_origins).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else ["*"],
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
def read_root():
    return {"status": "AI Stock Engine API (V3 Architecture) is online.", "version": "3.0.0"}

# Include all abstracted routes.
# IV&V C1: gate every route behind the optional API-key dependency. It is a
# no-op unless APP_API_KEY is set, so the same-origin frontend keeps working;
# set APP_API_KEY + send `x-api-key` to enforce hard auth.
from .auth import require_api_key
from fastapi import Depends
app.include_router(router, dependencies=[Depends(require_api_key)])
