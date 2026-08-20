import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, JSON, Text, UniqueConstraint, Index, Uuid, TypeDecorator
)
from sqlalchemy.orm import relationship
from database.database import Base

# ── D-1 fix ──────────────────────────────────────────────────────────────────
# SQLite treats NULL as distinct from every other NULL, so two rows with
# NULL user_id and the same market value both pass UniqueConstraint('user_id','market').
# Use a fixed sentinel UUID for system-owned (paper-trading) portfolios so the
# constraint actually prevents duplicate market rows.
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ── S-1 fix ──────────────────────────────────────────────────────────────────
# Transparent encrypt/decrypt of broker credentials via a SQLAlchemy
# TypeDecorator.  Values are encrypted on write and decrypted on read so
# the rest of the codebase sees plaintext; the DB file only ever stores
# ciphertext.
class EncryptedString(TypeDecorator):
    """Fernet-encrypted VARCHAR column."""
    impl          = String
    cache_ok      = True

    def process_bind_param(self, value, dialect):
        """Encrypt before writing to DB."""
        if value is None:
            return value
        from database.crypto import encrypt_credential
        return encrypt_credential(value)

    def process_result_value(self, value, dialect):
        """Decrypt after reading from DB."""
        if value is None:
            return value
        from database.crypto import decrypt_credential
        return decrypt_credential(value)

class User(Base):
    __tablename__ = 'users'
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    subscription = Column(String, default='free')
    broker = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    broker_accounts = relationship("BrokerAccount", back_populates="user")
    watchlists = relationship("Watchlist", back_populates="user")
    portfolios = relationship("Portfolio", back_populates="user")

class BrokerAccount(Base):
    __tablename__ = 'broker_accounts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Uuid, ForeignKey('users.id'))
    broker_name = Column(String, nullable=False)
    # S-1: credentials stored encrypted via EncryptedString TypeDecorator
    api_key       = Column(EncryptedString)
    secret        = Column(EncryptedString)
    access_token  = Column(EncryptedString)
    refresh_token = Column(EncryptedString)
    status = Column(String, default='inactive')
    last_login = Column(DateTime)

    user = relationship("User", back_populates="broker_accounts")

class Watchlist(Base):
    __tablename__ = 'watchlists'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Uuid, ForeignKey('users.id'))
    symbol = Column(String, nullable=False)
    exchange = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="watchlists")

class Symbol(Base):
    __tablename__ = 'symbols'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, unique=True, nullable=False)
    company_name = Column(String)
    sector = Column(String)
    industry = Column(String)
    exchange = Column(String)
    lot_size = Column(Integer, default=1)
    tick_size = Column(Float)
    currency = Column(String, default='USD')
    active = Column(Boolean, default=True)

class OHLCV(Base):
    __tablename__ = 'ohlcv'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    timeframe = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float)
    oi = Column(Float)
    vwap = Column(Float)

    __table_args__ = (
        Index('idx_ohlcv_symbol_id', 'symbol_id'),
        Index('idx_ohlcv_timestamp', 'timestamp'),
        Index('idx_ohlcv_symbol_time', 'symbol_id', 'timestamp'),
        Index('idx_ohlcv_timeframe', 'timeframe'),
        UniqueConstraint('symbol_id', 'timeframe', 'timestamp', name='uix_ohlcv_symbol_timeframe_timestamp')
    )

class Tick(Base):
    __tablename__ = 'ticks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    bid = Column(Float)
    ask = Column(Float)
    last = Column(Float)
    volume = Column(Float)

class Indicator(Base):
    __tablename__ = 'indicators'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    ema20 = Column(Float)
    ema50 = Column(Float)
    ema200 = Column(Float)
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    atr = Column(Float)
    adx = Column(Float)
    supertrend = Column(Float)
    boll_upper = Column(Float)
    boll_lower = Column(Float)
    obv = Column(Float)
    mfi = Column(Float)
    cci = Column(Float)
    stochastic = Column(Float)
    ichimoku = Column(JSON)

class SMC(Base):
    __tablename__ = 'smc'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    trend = Column(String)
    bos = Column(Boolean)
    choch = Column(Boolean)
    order_block = Column(JSON)
    fvg = Column(JSON)
    liquidity_zone = Column(JSON)
    breaker = Column(Boolean)
    mitigation = Column(Boolean)
    premium_discount = Column(String)

class News(Base):
    __tablename__ = 'news'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'))
    headline = Column(String, nullable=False)
    summary = Column(Text)
    url = Column(String)
    source = Column(String)
    published = Column(DateTime)
    sentiment = Column(Float)
    importance = Column(String)

class AIDecision(Base):
    __tablename__ = 'ai_decisions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    signal = Column(String, nullable=False)
    confidence = Column(Float)
    risk_score = Column(Float)
    expected_return = Column(Float)
    expected_loss = Column(Float)
    holding_time = Column(String)
    reason = Column(Text)

class CommitteeVote(Base):
    __tablename__ = 'committee_votes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(Integer, ForeignKey('ai_decisions.id'), nullable=False)
    agent_name = Column(String, nullable=False)
    vote = Column(String, nullable=False)
    confidence = Column(Float)
    weight = Column(Float)
    contribution = Column(Float)
    reason = Column(Text)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    broker_order_id = Column(String)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    user_id = Column(Uuid, ForeignKey('users.id'))
    side = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float)
    type = Column(String)
    status = Column(String)
    placed_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_order_user_id', 'user_id'),
    )

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id'))
    entry = Column(Float, nullable=False)
    exit = Column(Float)
    stop_loss = Column(Float)
    target = Column(Float)
    profit = Column(Float)
    commission = Column(Float)
    strategy = Column(String)
    confidence = Column(Float)
    
    __table_args__ = (
        Index('idx_trade_order_id', 'order_id'),
    )

class Portfolio(Base):
    __tablename__ = 'portfolio'
    id = Column(Integer, primary_key=True, autoincrement=True)
    # D-1: nullable=True but default=SYSTEM_USER_ID so the UniqueConstraint
    # ('user_id','market') actually works — NULL != NULL in SQLite, so two
    # NULL rows for the same market both pass. The sentinel UUID is equal to
    # itself, so the constraint correctly blocks duplicates.
    user_id = Column(Uuid, ForeignKey('users.id'), nullable=True,
                     default=lambda: SYSTEM_USER_ID)
    market = Column(String, default='US')
    cash = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    margin = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)
    state_data = Column(JSON, nullable=True)

    user = relationship("User", back_populates="portfolios")

    __table_args__ = (
        # One portfolio per (user, market) pair — not one per market globally.
        UniqueConstraint('user_id', 'market', name='uix_user_market'),
    )

class Holding(Base):
    __tablename__ = 'holdings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey('portfolio.id'), nullable=False)
    symbol_id = Column(Integer, ForeignKey('symbols.id'), nullable=False)
    quantity = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    current_price = Column(Float)
    market_value = Column(Float)

class Strategy(Base):
    __tablename__ = 'strategies'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    market_regime = Column(String)
    timeframe = Column(String)
    parameters = Column(JSON)
    success_rate = Column(Float)
    enabled = Column(Boolean, default=True)

class Backtest(Base):
    __tablename__ = 'backtests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    symbol_id = Column(Integer, ForeignKey('symbols.id'))
    from_date = Column(DateTime)
    to_date = Column(DateTime)
    net_profit = Column(Float)
    drawdown = Column(Float)
    win_rate = Column(Float)
    sharpe = Column(Float)
    sortino = Column(Float)
    profit_factor = Column(Float)

class RLFeedback(Base):
    __tablename__ = 'rl_feedback'
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey('trades.id'))
    reward = Column(Float)
    penalty = Column(Float)
    old_weight = Column(Float)
    new_weight = Column(Float)
    agent = Column(String)

class TradeJournal(Base):
    __tablename__ = 'trade_journal'
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey('trades.id'))
    entry_reason = Column(Text)
    exit_reason = Column(Text)
    mistakes = Column(Text)
    lessons = Column(Text)
    committee_breakdown = Column(JSON)
    chart_path = Column(String)
    report_path = Column(String)

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String)
    event = Column(String)
    importance = Column(String)
    forecast = Column(String)
    actual = Column(String)
    previous = Column(String)
    date = Column(DateTime)

class Log(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String, nullable=False)
    service = Column(String)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class RLWeight(Base):
    __tablename__ = 'rl_weights'
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String, default='US')
    regime = Column(String, nullable=False)
    agent_name = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    alpha = Column(Float, default=1.0)
    beta = Column(Float, default=1.0)
    
    __table_args__ = (
        UniqueConstraint('market', 'regime', 'agent_name', name='uix_market_regime_agent'),
    )
