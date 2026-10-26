"""
Unit tests for PaperExecutor.
Verifies balance accounting, slippage calculation, partial take-profits, and stop-loss exits.
"""
import unittest
import os
from src.execution.paper_executor import PaperExecutor


class TestPaperExecutor(unittest.TestCase):

    def setUp(self):
        self.db_path = f"test_paper_{self._testMethodName}_{os.getpid()}.db"
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        # Slippage = 100 bps = 1.0%
        self.executor = PaperExecutor(starting_balance_usd=1000.0, slippage_bps=100, db_path=self.db_path)

    def tearDown(self):
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_execute_buy_with_slippage(self):
        # Buy $100 of token at $1.00 base price
        pos = self.executor.execute_buy(
            token_mint="TOKEN_MINT_A",
            token_symbol="TOKEN_A",
            usd_size=100.0,
            current_price=1.00,
            copied_trader="trader_xyz",
        )
        self.assertIsNotNone(pos)
        self.assertEqual(self.executor.get_cash_balance(), 900.0)

        # Slippage +1.0% means entry price = $1.01
        self.assertAlmostEqual(pos.entry_price_usd, 1.01, places=3)
        self.assertAlmostEqual(pos.token_amount, 100.0 / 1.01, places=3)
        self.assertEqual(pos.status, "OPEN")

    def test_multi_level_take_profit(self):
        # Open $100 position at $1.00 (effective entry ~$1.01)
        pos = self.executor.execute_buy("TOKEN_MINT_B", "TOKEN_B", 100.0, 1.00, "trader_abc")

        # Price doubles to $2.02 (+100% gain)
        # Sell 50% partial TP
        realized_pnl = self.executor.execute_sell(pos, sell_pct=50.0, current_price=2.02, reason="TP Tier 1")

        self.assertGreater(realized_pnl, 45.0)  # ~$50 gain minus slippage
        self.assertGreater(self.executor.get_cash_balance(), 990.0)
        self.assertEqual(pos.status, "PARTIALLY_CLOSED")

        # Sell remaining 100% at $3.00
        realized_pnl_2 = self.executor.execute_sell(pos, sell_pct=100.0, current_price=3.00, reason="TP Final")
        self.assertGreater(realized_pnl_2, 0)
        self.assertEqual(len(self.executor.get_open_positions()), 0)

    def test_stop_loss_exit(self):
        pos = self.executor.execute_buy("TOKEN_MINT_C", "TOKEN_C", 100.0, 1.00, "trader_123")
        self.assertEqual(self.executor.get_cash_balance(), 900.0)

        # Token dumps to $0.60 (-40%)
        realized_loss = self.executor.execute_sell(pos, sell_pct=100.0, current_price=0.60, reason="Stop Loss")
        self.assertLess(realized_loss, -35.0)  # Loss around -$41
        self.assertEqual(len(self.executor.get_open_positions()), 0)
        self.assertEqual(pos.status, "CLOSED")


if __name__ == "__main__":
    unittest.main()
