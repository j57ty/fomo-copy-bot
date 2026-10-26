"""
Risk Management and Safety Circuit Breakers.
Enforces hard daily loss limit, max portfolio drawdown, position sizing, and kill switch.
"""
import os
import time
import logging
from typing import Tuple, Dict, Any, List
from src.config import BotConfig

logger = logging.getLogger("fomo_bot.risk")


class RiskManager:
    """
    Enforces non-negotiable safety rules:
    - Emergency Kill Switch
    - Daily Loss Limit (rolling 24h)
    - Peak Portfolio Drawdown limit
    - Maximum simultaneous open positions
    - Dynamic sizing guardrails
    """

    def __init__(self, config: BotConfig, starting_balance_usd: float = 1000.0):
        self.config = config
        self.starting_balance_usd = starting_balance_usd
        self.peak_portfolio_usd = starting_balance_usd
        self.kill_switch_triggered = config.kill_switch_active
        self.kill_switch_reason = "Configuration active" if config.kill_switch_active else ""
        
        # Realized trades log for rolling 24h loss calculation
        # Each entry: {"timestamp": int, "pnl_usd": float}
        self.trade_pnl_history: List[Dict[str, Any]] = []

    def check_kill_switch_file(self) -> bool:
        """Checks for presence of .killswitch file in working directory."""
        if os.path.exists(".killswitch") or os.path.exists("fomo-copy-bot/.killswitch"):
            self.kill_switch_triggered = True
            self.kill_switch_reason = "External .killswitch file detected"
            return True
        return False

    def trigger_kill_switch(self, reason: str = "Manual trigger"):
        """Activates emergency kill switch."""
        self.kill_switch_triggered = True
        self.kill_switch_reason = reason
        # Also drop a touch file for persistence
        try:
            with open(".killswitch", "w", encoding="utf-8") as f:
                f.write(f"Kill switch activated at {time.ctime()}: {reason}\n")
        except Exception:
            pass
        logger.critical("🚨 EMERGENCY KILL SWITCH ENGAGED: %s", reason)

    def reset_kill_switch(self):
        """Manually disengages kill switch."""
        self.kill_switch_triggered = False
        self.kill_switch_reason = ""
        for p in [".killswitch", "fomo-copy-bot/.killswitch"]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        logger.info("Kill switch disengaged by operator.")

    def record_closed_trade_pnl(self, pnl_usd: float):
        """Records realized PnL of a closed trade for rolling risk tracking."""
        self.trade_pnl_history.append({
            "timestamp": int(time.time()),
            "pnl_usd": pnl_usd,
        })

    def get_daily_realized_loss_usd(self) -> float:
        """Calculates total net realized loss in the last 24 hours."""
        now = int(time.time())
        day_ago = now - 86400
        # Filter trades within last 24h
        recent_trades = [t for t in self.trade_pnl_history if t["timestamp"] >= day_ago]
        total_pnl = sum(t["pnl_usd"] for t in recent_trades)
        # Return positive number for losses
        if total_pnl < 0:
            return abs(total_pnl)
        return 0.0

    def update_portfolio_peak(self, current_total_usd: float):
        """Updates all-time high portfolio value."""
        if current_total_usd > self.peak_portfolio_usd:
            self.peak_portfolio_usd = current_total_usd

    def get_current_drawdown_pct(self, current_total_usd: float) -> float:
        """Calculates drawdown percentage from peak."""
        self.update_portfolio_peak(current_total_usd)
        if self.peak_portfolio_usd <= 0:
            return 0.0
        drawdown = ((self.peak_portfolio_usd - current_total_usd) / self.peak_portfolio_usd) * 100.0
        return max(0.0, drawdown)

    def can_open_position(
        self,
        current_open_positions: int,
        cash_balance_usd: float,
        total_portfolio_usd: float,
    ) -> Tuple[bool, str, float]:
        """
        Evaluates whether a new position can be opened.
        Returns: (allowed: bool, reason: str, approved_usd_size: float)
        """
        # 1. Kill switch check
        self.check_kill_switch_file()
        if self.kill_switch_triggered:
            return False, f"Kill switch active ({self.kill_switch_reason})", 0.0

        # 2. Maximum open positions check
        if current_open_positions >= self.config.max_open_positions:
            return False, f"Max open positions reached ({current_open_positions}/{self.config.max_open_positions})", 0.0

        # 3. Hard daily loss check
        daily_loss = self.get_daily_realized_loss_usd()
        if daily_loss >= self.config.max_daily_loss_usd:
            return (
                False,
                f"Daily loss limit breached: -${daily_loss:.2f} >= limit ${self.config.max_daily_loss_usd:.2f}",
                0.0,
            )

        # 4. Maximum portfolio drawdown check
        dd_pct = self.get_current_drawdown_pct(total_portfolio_usd)
        if dd_pct >= self.config.max_portfolio_drawdown_pct:
            return (
                False,
                f"Max portfolio drawdown breached: {dd_pct:.2f}% >= limit {self.config.max_portfolio_drawdown_pct:.2f}%",
                0.0,
            )

        # 5. Position sizing calculation
        if self.config.size_mode == "percent":
            target_size = (total_portfolio_usd * self.config.portfolio_pct_per_trade) / 100.0
        else:
            target_size = self.config.trade_size_usd

        # 6. Cash availability check
        if cash_balance_usd < 5.0:
            return False, f"Insufficient cash balance: ${cash_balance_usd:.2f} available", 0.0

        if target_size > cash_balance_usd:
            # Scale down to available cash if at least $10
            if cash_balance_usd >= 10.0:
                approved_size = cash_balance_usd * 0.95  # Leave 5% buffer for fees/gas
                logger.info("Scaling trade size from $%.2f to available cash buffer $%.2f", target_size, approved_size)
                return True, "Approved (scaled to available cash)", round(approved_size, 2)
            else:
                return False, f"Trade size ${target_size:.2f} exceeds available cash ${cash_balance_usd:.2f}", 0.0

        return True, "Risk checks passed", round(target_size, 2)
