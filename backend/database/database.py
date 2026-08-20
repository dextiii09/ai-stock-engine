import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

# Redis is OPTIONAL -- it is only used by get_redis(), which no core module
# depends on. A missing redis package must never break DB persistence
# (previously this import crashed the whole module, leaving
# AsyncSessionLocal undefined and silently disabling ALL SQLite writes).
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_stock")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# SQLAlchemy Setup -- SQLite in WAL mode.
_is_sqlite = "sqlite" in DATABASE_URL.lower()
_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    # timeout=60 -> aiosqlite waits up to 60 s before raising OperationalError
    _engine_kwargs["connect_args"] = {"timeout": 60}
    # Pool sizing: the previous pool_size=1/max_overflow=0 shared ONE connection
    # across all 5 trading engines AND the dashboard's constant read polling. A
    # single slow write (e.g. an RL mini-retrain during a regime switch) then
    # blocked everything else until pool_timeout, and a force_close write was seen
    # failing with "QueuePool limit of size 1 overflow 0 ... timed out (90s)".
    # WAL mode already permits concurrent readers + one writer, and writes are
    # serialised at the app layer (per-engine DB locks) plus busy_timeout=60s, so
    # a single-connection pool is unnecessary and actively harmful. Give reads and
    # independent sessions room so they can't starve a write.
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10
    _engine_kwargs["pool_timeout"] = 30  # fail faster & louder if truly saturated
    _engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

if _is_sqlite:
    # WAL mode allows concurrent readers + 1 writer, vastly reducing lock conflicts
    from sqlalchemy import event as _event

    @_event.listens_for(engine.sync_engine, "connect")
    def _enable_wal(dbapi_conn, connection_record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=60000")  # 60 s retry
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")
        dbapi_conn.execute("PRAGMA cache_size=-8000")    # 8 MB page cache

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Redis Setup (optional -- pool is created lazily so a missing/unreachable
# Redis server never affects startup)
redis_pool = (
    redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    if REDIS_AVAILABLE else None
)


async def get_redis():
    if not REDIS_AVAILABLE:
        raise RuntimeError("Redis is not installed -- get_redis() is unavailable.")
    return redis.Redis(connection_pool=redis_pool)
