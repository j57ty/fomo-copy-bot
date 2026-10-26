"""
Integration tests for CopyEngine.
Verifies end-to-end flow: StalkChain trader event -> filter -> risk check -> fill -> TP exit.
"""
import unittest
import os
import time
from src.config import BotConfig, TakeProfitConfig
from src.data.models import SwapEvent
from src.engine.copy_engine import CopyEngine
from src.execution.paper_executor import PaperExecutor


class TestCopyEngineIntegration(unittest.TestCase):

    def setUp(self):
        self.db_path = f"test_engine_{self._testMethodName}_{os.getpid()}.db"
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

        self.config = BotConfig(
            mode="paper",
            trade_size_usd=50.0,
            max_open_positions=3,
            max_chase_pct=5.0,
            copy_first_buy_only=True,
            stop_loss_pct=-35.0,
            take_profit_levels=[
                TakeProfitConfig(trigger_pct=100.0, sell_pct=50.0),
                TakeProfitConfig(trigger_pct=300.0, sell_pct=100.0),
            ],
            followed_traders=["9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"],
        )
        self.executor = PaperExecutor(starting_balance_usd=1000.0, db_path=self.db_path)
        self.engine = CopyEngine(self.config, executor=self.executor)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        if os.path.exists(".killswitch"):
            os.remove(".killswitch")

    def test_end_to_end_copy_and_exit(self):
        # 1. Incoming buy event from followed trader
        event = SwapEvent(
            tx_hash="tx_fomo_whale_001",
            timestamp=int(time.time()),
            trader_address="9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
            side="BUY",
            token_mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            token_symbol="BONK",
            amount_token=10000.0,
            amount_usd=500.0,
            price_usd=0.05,
            is_first_buy=True,
            liquidity_usd=150000.0,
            market_cap_usd=2500000.0,
        )

        # Process the event
        self.engine.process_new_events([event])

        # Verify position opened
        open_positions = self.executor.get_open_positions()
        self.assertEqual(len(open_positions), 1)
        pos = open_positions[0]
        self.assertEqual(pos.token_symbol, "BONK")
        self.assertAlmostEqual(pos.initial_usd_size, 50.0, places=1)
        self.assertEqual(self.executor.get_cash_balance(), 950.0)

        # 2. Token pumps +120% (price goes from ~0.05 to 0.11)
        # Mock price lookup returning 0.11
        self.engine.stalkchain.mock_data.tokens[pos.token_mint].price_usd = 0.11
        self.engine.check_exits()

        # TP Tier 1 should have executed (sold 50%)
        self.assertEqual(pos.status, "PARTIALLY_CLOSED")
        self.assertIn(0, pos.tp_levels_executed)
        self.assertGreater(self.executor.get_cash_balance(), 950.0 + 50.0)

        # 3. Duplicate buy event should be skipped (first_buy_only or cooldown)
        self.engine.process_new_events([event])
        self.assertEqual(len(self.executor.get_open_positions()), 1)
        last_log = self.engine.decision_logs[-1]
        self.assertEqual(last_log["action"], "SKIP")
        self.assertTrue(
            "first_buy_only" in last_log["reason"].lower() or "cooldown" in last_log["reason"].lower()
        )


if __name__ == "__main__":
    unittest.main()
