"""
Trade Filter Engine.
Applies chase %, liquidity floor, market cap boundaries, first-buy-only, and cooldowns.
"""
import time
import logging
from typing import Tuple, Dict
from src.config import BotConfig
from src.data.models import SwapEvent

logger = logging.getLogger("fomo_bot.filter")


class FilterEngine:
    """
    Evaluates incoming trader events against user safety & quality filters.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        # Map of token_mint -> last_bought_timestamp
        self.token_last_bought: Dict[str, int] = {}
        # Map of (trader, token_mint) -> count of buys observed
        self.trader_token_buys: Dict[Tuple[str, str], int] = {}

    def record_buy_execution(self, token_mint: str, trader_address: str):
        """Records a buy execution to enforce cooldowns and first-buy tracking."""
        now = int(time.time())
        self.token_last_bought[token_mint] = now
        key = (trader_address, token_mint)
        self.trader_token_buys[key] = self.trader_token_buys.get(key, 0) + 1

    def evaluate_entry(self, event: SwapEvent, current_market_price: float) -> Tuple[bool, str]:
        """
        Evaluates whether an incoming trader buy event meets all filter criteria.
        Returns (passed: bool, reason: str).
        """
        # 1. Side check: only copy BUY actions
        if event.side != "BUY":
            return False, f"Event is a {event.side}, not a BUY"

        # 2. First-Buy-Only Filter
        if self.config.copy_first_buy_only:
            # If the event itself is flagged as not first buy, or we previously saw a buy
            prior_buys = self.trader_token_buys.get((event.trader_address, event.token_mint), 0)
            if prior_buys > 0 or not event.is_first_buy:
                return False, f"Trader has already bought {event.token_symbol} previously (first_buy_only=true)"

        # 3. Token Cooldown Check
        now = int(time.time())
        last_bought = self.token_last_bought.get(event.token_mint, 0)
        cooldown = self.config.token_cooldown_seconds
        if (now - last_bought) < cooldown:
            remaining = cooldown - (now - last_bought)
            return False, f"Token cooldown active for {event.token_symbol} ({remaining}s remaining)"

        # 4. Chase Percentage Guard
        if event.price_usd > 0 and current_market_price > 0:
            chase_pct = ((current_market_price - event.price_usd) / event.price_usd) * 100.0
            if chase_pct > self.config.max_chase_pct:
                return (
                    False,
                    f"Chase % exceeded: price jumped {chase_pct:.2f}% since fill > max {self.config.max_chase_pct:.1f}%",
                )

        # 5. Liquidity Floor Filter
        if event.liquidity_usd > 0 and event.liquidity_usd < self.config.min_liquidity_usd:
            return (
                False,
                f"Liquidity too low: ${event.liquidity_usd:,.0f} < min ${self.config.min_liquidity_usd:,.0f}",
            )

        # 6. Minimum Market Cap Filter
        if event.market_cap_usd > 0 and event.market_cap_usd < self.config.min_market_cap_usd:
            return (
                False,
                f"Market cap too low: ${event.market_cap_usd:,.0f} < min ${self.config.min_market_cap_usd:,.0f}",
            )

        # 7. Maximum Market Cap Filter
        if event.market_cap_usd > 0 and event.market_cap_usd > self.config.max_market_cap_usd:
            return (
                False,
                f"Market cap too high: ${event.market_cap_usd:,.0f} > max ${self.config.max_market_cap_usd:,.0f}",
            )

        return True, "All filter conditions passed"
