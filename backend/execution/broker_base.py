"""
Abstract broker interface.
All broker implementations must subclass BrokerBase.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple


class BrokerBase(ABC):
    """
    Abstract base class for all broker integrations.
    The SmartExecutionEngine calls these methods to place / close orders.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable broker name (e.g. 'Paper', 'Zerodha', 'IBKR')."""

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """Returns True if this broker executes real orders."""

    @abstractmethod
    def buy(
        self,
        symbol: str,
        qty: int,
        price: float,
        order_type: str = "MARKET",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Place a buy/long order.

        Returns:
            (success, message, broker_order_id)
        """

    @abstractmethod
    def sell(
        self,
        symbol: str,
        qty: int,
        price: float,
        order_type: str = "MARKET",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Place a sell / close-long order.

        Returns:
            (success, message, broker_order_id)
        """

    @abstractmethod
    def short(
        self,
        symbol: str,
        qty: int,
        price: float,
        order_type: str = "MARKET",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Place a short-sell order.

        Returns:
            (success, message, broker_order_id)
        """

    @abstractmethod
    def cover(
        self,
        symbol: str,
        qty: int,
        price: float,
        order_type: str = "MARKET",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Cover (buy-to-close) a short position.

        Returns:
            (success, message, broker_order_id)
        """

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        """
        Round an internal (possibly fractional) quantity to this broker's
        tradeable lot size for `symbol`.

        IV&V C2 fix: the engine previously passed `int(qty)` directly to live
        brokers, so a fractional internal size (e.g. 0.0677 BTC, 0.17 micro-
        contracts) silently became a 0-unit order while the engine booked the
        full position — an immediate book/broker desync.

        Contract:
          * Return the broker-legal quantity (may be fractional if the broker
            supports it).
          * Return 0.0 (or less) to signal a SUB-LOT order that the caller must
            reject/log rather than silently truncate.

        Default: identity (fractional-friendly, e.g. Paper/crypto). Integer-lot
        brokers (equities, futures contracts) override to round to whole units.
        """
        return float(qty)

    def get_account_info(self) -> Dict[str, Any]:
        """
        Optional: return live account balance / margin info.
        Override in concrete brokers that support it.
        """
        return {}

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        """Cancel a pending order. Override if broker supports it."""
        return False, "Order cancellation not supported by this broker."
