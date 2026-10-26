"""
Realistic mock data generator for FOMO (fomo.family) traders and StalkChain events.
Enables offline paper trading, automated testing, and deterministic scenario simulation.
"""
import time
import random
from typing import List, Dict, Any, Optional
from src.data.models import Trader, SwapEvent, TokenInfo

MOCK_FOMO_TRADERS: List[Dict[str, Any]] = [
    {
        "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        "handle": "sol_whale_007",
        "pnl_usd": 142500.50,
        "pnl_pct": 340.2,
        "win_rate": 78.4,
        "trade_count": 92,
        "timeframe": "7d",
        "followers": 1420,
        "rank": 1,
    },
    {
        "address": "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH",
        "handle": "fomo_sniper_sol",
        "pnl_usd": 98400.20,
        "pnl_pct": 215.0,
        "win_rate": 71.2,
        "trade_count": 145,
        "timeframe": "7d",
        "followers": 980,
        "rank": 2,
    },
    {
        "address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "handle": "pump_hunter_99",
        "pnl_usd": 67200.00,
        "pnl_pct": 182.5,
        "win_rate": 65.0,
        "trade_count": 110,
        "timeframe": "7d",
        "followers": 750,
        "rank": 3,
    },
    {
        "address": "3KzQWj1XG8mK2q2x9bZc4k7n9wX8mK2q2x9bZc4k7n9w",
        "handle": "alpha_scout",
        "pnl_usd": 45100.80,
        "pnl_pct": 120.3,
        "win_rate": 62.5,
        "trade_count": 78,
        "timeframe": "7d",
        "followers": 510,
        "rank": 4,
    },
    {
        "address": "7YtAWWM9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9",
        "handle": "gem_finder_x",
        "pnl_usd": 32800.00,
        "pnl_pct": 95.4,
        "win_rate": 59.0,
        "trade_count": 64,
        "timeframe": "7d",
        "followers": 320,
        "rank": 5,
    },
]

MOCK_TOKENS: List[Dict[str, Any]] = [
    {
        "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "symbol": "BONK",
        "name": "Bonk",
        "price_usd": 0.0000224,
        "market_cap_usd": 1500000.0,
        "liquidity_usd": 350000.0,
    },
    {
        "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "symbol": "WIF",
        "name": "dogwifhat",
        "price_usd": 2.45,
        "market_cap_usd": 24500000.0,
        "liquidity_usd": 1200000.0,
    },
    {
        "mint": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "symbol": "POPCAT",
        "name": "Popcat",
        "price_usd": 0.85,
        "market_cap_usd": 8500000.0,
        "liquidity_usd": 420000.0,
    },
    {
        "mint": "MEW1gQWJ3nEXg2qYXk7j8r5t8y2u3i4o5p6a7s8d9f0",
        "symbol": "MEW",
        "name": "cat in a dogs world",
        "price_usd": 0.0084,
        "market_cap_usd": 450000.0,
        "liquidity_usd": 85000.0,
    },
    {
        "mint": "FOMO1111111111111111111111111111111111111111",
        "symbol": "FOMO",
        "name": "FOMO Family Token",
        "price_usd": 0.125,
        "market_cap_usd": 1250000.0,
        "liquidity_usd": 180000.0,
    },
    {
        "mint": "RUG9999999999999999999999999999999999999999",
        "symbol": "RUGGY",
        "name": "Low Liquidity Trap",
        "price_usd": 0.0001,
        "market_cap_usd": 12000.0,      # Low mcap (should fail filter)
        "liquidity_usd": 4500.0,        # Low liquidity (should fail filter)
    },
]


class MockStalkChainData:
    """Simulates the StalkChain MCP server state for FOMO traders."""

    def __init__(self):
        self.traders = [Trader(**t) for t in MOCK_FOMO_TRADERS]
        self.tokens = {t["mint"]: TokenInfo(**t) for t in MOCK_TOKENS}
        self.trade_history: List[SwapEvent] = []
        self._seed_initial_history()

    def _seed_initial_history(self):
        now = int(time.time())
        # Seed a few prior swaps for each trader
        for trader in self.traders:
            token = random.choice(list(self.tokens.values())[:4])
            event = SwapEvent(
                tx_hash=f"tx_{int(time.time())}_{random.randint(1000, 9999)}",
                timestamp=now - random.randint(100, 3600),
                trader_address=trader.address,
                side="BUY",
                token_mint=token.mint,
                token_symbol=token.symbol,
                amount_token=1000.0,
                amount_usd=random.uniform(50, 500),
                price_usd=token.price_usd,
                is_first_buy=True,
                liquidity_usd=token.liquidity_usd,
                market_cap_usd=token.market_cap_usd,
            )
            self.trade_history.append(event)

    def get_leaderboard(self, timeframe: str = "7d", limit: int = 10) -> List[Trader]:
        # Sort by pnl_usd descending
        sorted_traders = sorted(self.traders, key=lambda t: t.pnl_usd, reverse=True)
        for i, t in enumerate(sorted_traders, 1):
            t.rank = i
            t.timeframe = timeframe
        return sorted_traders[:limit]

    def resolve_trader(self, address_or_handle: str) -> Optional[Trader]:
        for t in self.traders:
            if t.address == address_or_handle or t.handle.lower() == address_or_handle.lower():
                return t
        return None

    def get_trader_swaps(self, trader_address: str, limit: int = 10) -> List[SwapEvent]:
        swaps = [s for s in self.trade_history if s.trader_address == trader_address]
        return sorted(swaps, key=lambda s: s.timestamp, reverse=True)[:limit]

    def get_token_price(self, mint: str) -> float:
        token = self.tokens.get(mint)
        if token:
            # Add minor price noise (+/- 0.5%)
            drift = 1.0 + random.uniform(-0.005, 0.005)
            return token.price_usd * drift
        return 0.0

    def simulate_new_swap(self, trader_address: str, token_mint: Optional[str] = None, side: str = "BUY") -> SwapEvent:
        """Simulates a live on-chain swap event by a tracked trader."""
        if not token_mint:
            token = random.choice(list(self.tokens.values())[:5])
        else:
            token = self.tokens.get(token_mint, list(self.tokens.values())[0])

        current_price = token.price_usd * random.uniform(0.99, 1.02)
        amount_usd = random.uniform(100.0, 1000.0)
        amount_token = amount_usd / current_price if current_price > 0 else 0

        # Check if first buy
        prev_buys = [s for s in self.trade_history if s.trader_address == trader_address and s.token_mint == token.mint and s.side == "BUY"]
        is_first_buy = len(prev_buys) == 0

        event = SwapEvent(
            tx_hash=f"tx_{int(time.time())}_{random.randint(1000, 9999)}",
            timestamp=int(time.time()),
            trader_address=trader_address,
            side=side,
            token_mint=token.mint,
            token_symbol=token.symbol,
            amount_token=round(amount_token, 4),
            amount_usd=round(amount_usd, 2),
            price_usd=current_price,
            is_first_buy=is_first_buy,
            liquidity_usd=token.liquidity_usd,
            market_cap_usd=token.market_cap_usd,
        )
        self.trade_history.append(event)
        return event
