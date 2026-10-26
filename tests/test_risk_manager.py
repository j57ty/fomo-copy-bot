"""
Unit tests for RiskManager.
Verifies daily loss limit, portfolio drawdown, max open positions, and kill switch.
"""
import unittest
import os
from src.config import BotConfig
from src.risk.risk_manager import RiskManager


class TestRiskManager(unittest.TestCase):

    def setUp(self):
        self.config = BotConfig(
            max_daily_loss_usd=100.0,
            max_portfolio_drawdown_pct=20.0,
            max_open_positions=3,
            trade_size_usd=50.0,
            kill_switch_active=False,
        )
        self.risk = RiskManager(self.config, starting_balance_usd=1000.0)

    def tearDown(self):
        if os.path.exists(".killswitch"):
            os.remove(".killswitch")

    def test_kill_switch_engagement(self):
        # Default state
        allowed, reason, size = self.risk.can_open_position(0, 1000.0, 1000.0)
        self.assertTrue(allowed)

        # Trigger kill switch
        self.risk.trigger_kill_switch("Manual test trigger")
        self.assertTrue(self.risk.kill_switch_triggered)
        allowed, reason, size = self.risk.can_open_position(0, 1000.0, 1000.0)
        self.assertFalse(allowed)
        self.assertIn("Kill switch active", reason)

        # Reset kill switch
        self.risk.reset_kill_switch()
        self.assertFalse(self.risk.kill_switch_triggered)
        allowed, reason, size = self.risk.can_open_position(0, 1000.0, 1000.0)
        self.assertTrue(allowed)

    def test_daily_loss_limit(self):
        # Record a loss below limit
        self.risk.record_closed_trade_pnl(-40.0)
        allowed, reason, size = self.risk.can_open_position(0, 960.0, 960.0)
        self.assertTrue(allowed)

        # Record another loss breaching $100 limit
        self.risk.record_closed_trade_pnl(-65.0)  # Total loss = $105
        allowed, reason, size = self.risk.can_open_position(0, 895.0, 895.0)
        self.assertFalse(allowed)
        self.assertIn("Daily loss limit breached", reason)

    def test_portfolio_drawdown_limit(self):
        # Portfolio reaches peak of $2,000
        self.risk.update_portfolio_peak(2000.0)

        # Drops to $1,800 (10% drawdown < 20% limit)
        allowed, reason, size = self.risk.can_open_position(0, 1800.0, 1800.0)
        self.assertTrue(allowed)

        # Drops to $1,500 (25% drawdown >= 20% limit)
        allowed, reason, size = self.risk.can_open_position(0, 1500.0, 1500.0)
        self.assertFalse(allowed)
        self.assertIn("Max portfolio drawdown breached", reason)

    def test_max_open_positions(self):
        # Under limit (2/3)
        allowed, reason, size = self.risk.can_open_position(2, 500.0, 1000.0)
        self.assertTrue(allowed)

        # At limit (3/3)
        allowed, reason, size = self.risk.can_open_position(3, 500.0, 1000.0)
        self.assertFalse(allowed)
        self.assertIn("Max open positions reached", reason)

    def test_position_sizing_cash_buffer(self):
        # Sufficient cash
        allowed, reason, size = self.risk.can_open_position(0, 500.0, 1000.0)
        self.assertTrue(allowed)
        self.assertEqual(size, 50.0)

        # Low cash: scales down
        allowed, reason, size = self.risk.can_open_position(0, 40.0, 1000.0)
        self.assertTrue(allowed)
        self.assertLess(size, 40.0)

        # Insufficient cash (< $5)
        allowed, reason, size = self.risk.can_open_position(0, 4.0, 1000.0)
        self.assertFalse(allowed)
        self.assertIn("Insufficient cash balance", reason)


if __name__ == "__main__":
    unittest.main()
