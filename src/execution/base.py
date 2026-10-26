"""
Base Executor abstract class.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Callable
from src.data.models import Position


class BaseExecutor(ABC):

    @abstractmethod
    def get_cash_balance(self) -> float:
        """Returns currently available cash (USD/USDC/SOL) for new trades."""
        pass

    @abstractmethod
    def get_open_positions(self) -> List[Position]:
        """Returns currently open positions."""
        pass

    @abstractmethod
    def execute_buy(
        self,
        token_mint: str,
        token_symbol: str,
        usd_size: float,
        current_price: float,
        copied_trader: str,
    ) -> Optional[Position]:
        """Executes a buy order to open or add to a position."""
        pass

    @abstractmethod
    def execute_sell(
        self,
        position: Position,
        sell_pct: float,
        current_price: float,
        reason: str,
    ) -> float:
        """Executes a full or partial sell order. Returns realized PnL in USD."""
        pass

    @abstractmethod
    def update_positions_market_prices(self, price_lookup: Callable[[str], float]):
        """Updates market prices and unrealized PnL across all open positions."""
        pass

    @abstractmethod
    def get_total_portfolio_value(self) -> float:
        """Calculates total portfolio value (cash + mark-to-market positions)."""
        pass
