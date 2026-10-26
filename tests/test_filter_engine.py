"""
Unit tests for FilterEngine.
Verifies chase percentage, liquidity floor, market cap range, first-buy-only, and cooldowns.
"""
import unittest
import time
from src.config import BotConfig
from src.data.models import SwapEvent
from src.engine.filter_engine import FilterEngine


class TestFilterEngine(unittest.TestCase):

    def setUp(self):
        self.config = BotConfig(
            max_chase_pct=5.0,
            min_liquidity_usd=25000.0,
            min_market_cap_usd=50000.0,
            max_market_cap_usd=10000000.0,
            copy_first_buy_only=True,
            token_cooldown_seconds=300,
        )
        self.engine = FilterEngine(self.config)

    def _create_event(self, **kwargs) -> SwapEvent:
        defaults = {
            "tx_hash": "tx_test_123",
            "timestamp": int(time.time()),
            "trader_address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
            "side": "BUY",
            "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            "token_symbol": "BONK",
            "amount_token": 1000.0,
            "amount_usd": 100.0,
            "price_usd": 1.0,
            "is_first_buy": True,
            "liquidity_usd": 50000.0,
            "market_cap_usd": 500000.0,
        }
        defaults.update(kwargs)
        return SwapEvent(**defaults)

    def test_valid_event_passes(self):
        ev = self._create_event()
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.02)
        self.assertTrue(passed)
        self.assertEqual(reason, "All filter conditions passed")

    def test_chase_percentage_filter(self):
        # Trader bought at $1.00, current price is $1.08 (+8.0% > 5% limit) -> REJECT
        ev = self._create_event(price_usd=1.00)
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.08)
        self.assertFalse(passed)
        self.assertIn("Chase % exceeded", reason)

        # Current price is $1.03 (+3.0% <= 5% limit) -> PASS
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.03)
        self.assertTrue(passed)

    def test_liquidity_floor_filter(self):
        # Low liquidity token ($10k < $25k limit) -> REJECT
        ev = self._create_event(liquidity_usd=10000.0)
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertFalse(passed)
        self.assertIn("Liquidity too low", reason)

    def test_market_cap_filters(self):
        # Ultra low mcap ($20k < $50k min) -> REJECT
        ev = self._create_event(market_cap_usd=20000.0)
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertFalse(passed)
        self.assertIn("Market cap too low", reason)

        # Huge mcap ($20M > $10M max) -> REJECT
        ev = self._create_event(market_cap_usd=20000000.0)
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertFalse(passed)
        self.assertIn("Market cap too high", reason)

    def test_first_buy_only_filter(self):
        # First buy -> PASS
        ev = self._create_event(is_first_buy=True)
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertTrue(passed)

        # Record the buy
        self.engine.record_buy_execution(ev.token_mint, ev.trader_address)

        # Second buy by same trader -> REJECT
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertFalse(passed)
        self.assertIn("already bought", reason)

    def test_token_cooldown_filter(self):
        ev = self._create_event(token_mint="DIFFERENT_MINT_111", is_first_buy=True, trader_address="trader_alpha")
        passed, reason = self.engine.evaluate_entry(ev, current_market_price=1.0)
        self.assertTrue(passed)

        # Record buy
        self.engine.record_buy_execution(ev.token_mint, ev.trader_address)

        # Different trader buys the same token during global token cooldown -> REJECT
        ev2 = self._create_event(token_mint="DIFFERENT_MINT_111", is_first_buy=True, trader_address="trader_beta")
        passed, reason = self.engine.evaluate_entry(ev2, current_market_price=1.0)
        self.assertFalse(passed)
        self.assertIn("Token cooldown active", reason)


if __name__ == "__main__":
    unittest.main()
