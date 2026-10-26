"""
Core data models for FOMO Copy-Trading Bot.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import time
import uuid


@dataclass
class Trader:
    address: str
    handle: str
    pnl_usd: float
    pnl_pct: float
    win_rate: float = 0.0
    trade_count: int = 0
    timeframe: str = "7d"
    chain: str = "solana"
    followers: int = 0
    rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TokenInfo:
    mint: str
    symbol: str
    name: str = ""
    decimals: int = 6
    price_usd: float = 0.0
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    chain: str = "solana"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SwapEvent:
    tx_hash: str
    timestamp: int
    trader_address: str
    side: str  # "BUY" or "SELL"
    token_mint: str
    token_symbol: str
    amount_token: float
    amount_usd: float
    price_usd: float
    chain: str = "solana"
    is_first_buy: bool = False
    liquidity_usd: float = 0.0
    market_cap_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TakeProfitLevel:
    trigger_pct: float  # e.g. 100.0 means +100% gain
    sell_pct: float     # e.g. 50.0 means sell 50% of remaining bag

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Position:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    token_mint: str = ""
    token_symbol: str = ""
    copied_trader: str = ""
    entry_timestamp: int = field(default_factory=lambda: int(time.time()))
    entry_price_usd: float = 0.0
    current_price_usd: float = 0.0
    token_amount: float = 0.0
    initial_usd_size: float = 0.0
    current_usd_value: float = 0.0
    unrealized_pnl_usd: float = 0.0
    unrealized_pnl_pct: float = 0.0
    realized_pnl_usd: float = 0.0
    tp_levels_executed: List[int] = field(default_factory=list)
    status: str = "OPEN"  # OPEN, CLOSED, PARTIALLY_CLOSED
    close_reason: Optional[str] = None
    close_timestamp: Optional[int] = None

    def update_price(self, new_price: float):
        if new_price <= 0:
            return
        self.current_price_usd = new_price
        self.current_usd_value = self.token_amount * new_price
        if self.entry_price_usd > 0:
            self.unrealized_pnl_pct = ((new_price - self.entry_price_usd) / self.entry_price_usd) * 100.0
            self.unrealized_pnl_usd = (new_price - self.entry_price_usd) * self.token_amount

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeDecision:
    action: str  # "EXECUTE_BUY", "EXECUTE_SELL", "SKIP"
    reason: str
    swap_event: Optional[SwapEvent] = None
    position: Optional[Position] = None
    usd_size: float = 0.0
    sell_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        if self.swap_event:
            res["swap_event"] = self.swap_event.to_dict()
        if self.position:
            res["position"] = self.position.to_dict()
        return res


@dataclass
class BotStatus:
    mode: str = "paper"  # "paper" or "live"
    is_paused: bool = False
    kill_switch_active: bool = False
    starting_balance_usd: float = 1000.0
    cash_balance_usd: float = 1000.0
    total_portfolio_usd: float = 1000.0
    peak_portfolio_usd: float = 1000.0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    daily_realized_pnl_usd: float = 0.0
    current_drawdown_pct: float = 0.0
    open_positions_count: int = 0
    followed_traders: List[str] = field(default_factory=list)
    last_update_ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
