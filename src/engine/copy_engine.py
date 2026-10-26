"""
Core Copy-Trading Engine.
Coordinates StalkChain data stream, risk manager, filter engine, and execution layer.
"""
import time
import logging
from typing import List, Dict, Any, Optional
from src.config import BotConfig
from src.data.models import Position, SwapEvent, BotStatus, Trader
from src.data.stalkchain_mcp import StalkChainClient
from src.risk.risk_manager import RiskManager
from src.engine.filter_engine import FilterEngine
from src.execution.base import BaseExecutor
from src.execution.paper_executor import PaperExecutor
from src.execution.solana_executor import SolanaLiveExecutor
from src.notifier.telegram_notifier import TelegramNotifier

logger = logging.getLogger("fomo_bot.engine")


class CopyEngine:
    """
    Main orchestrator for FOMO copy-trading bot.
    """

    def __init__(self, config: BotConfig, executor: Optional[BaseExecutor] = None):
        self.config = config
        self.stalkchain = StalkChainClient(
            mcp_url=config.stalkchain_mcp_url,
            api_key=config.stalkchain_api_key,
        )

        # Initialize Executor based on mode
        if executor:
            self.executor = executor
        else:
            if config.mode == "live":
                self.executor = SolanaLiveExecutor(config)
            else:
                self.executor = PaperExecutor(
                    starting_balance_usd=config.starting_paper_balance_usd,
                    slippage_bps=config.slippage_bps,
                )

        self.risk_manager = RiskManager(
            config=config,
            starting_balance_usd=self.executor.get_total_portfolio_value(),
        )
        self.filter_engine = FilterEngine(config)
        self.notifier = TelegramNotifier(config)

        self.is_running: bool = False
        self.decision_logs: List[Dict[str, Any]] = []
        self.last_poll_ts: int = int(time.time()) - 300  # Start 5 mins back

        self._init_followed_traders()

    def _init_followed_traders(self):
        """Initializes list of followed traders from config or top StalkChain leaderboard."""
        if not self.config.followed_traders and self.config.auto_sync_top_traders:
            logger.info("Auto-syncing top FOMO traders from StalkChain leaderboard...")
            top_traders = self.stalkchain.get_fomo_leaderboard(
                timeframe=self.config.leaderboard_timeframe,
                limit=self.config.top_traders_count,
            )
            self.config.followed_traders = [t.address for t in top_traders]
            logger.info("Auto-synced %d top traders: %s", len(self.config.followed_traders), self.config.followed_traders)
        elif not self.config.followed_traders:
            # Fallback to default mock traders if completely empty
            top_traders = self.stalkchain.get_fomo_leaderboard(limit=3)
            self.config.followed_traders = [t.address for t in top_traders]
            logger.info("Loaded default traders: %s", self.config.followed_traders)

    def log_decision(self, action: str, reason: str, details: Optional[Dict[str, Any]] = None):
        """Records structured audit log of all trade decisions and skips."""
        entry = {
            "timestamp": int(time.time()),
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "action": action,
            "reason": reason,
            "details": details or {},
        }
        self.decision_logs.append(entry)
        if len(self.decision_logs) > 500:
            self.decision_logs = self.decision_logs[-250:]

        level = logging.INFO if action.startswith("EXECUTE") else logging.DEBUG
        logger.log(level, "[DECISION] %s | %s | %s", action, reason, details or "")

    def check_exits(self):
        """
        Evaluates active positions for independent Stop-Loss and multi-tier Take-Profit exits.
        Does NOT rely on the copied trader's exits unless mirror_sells is explicitly enabled.
        """
        # 1. Update prices for all positions
        self.executor.update_positions_market_prices(self.stalkchain.get_token_price)
        open_positions = self.executor.get_open_positions()

        for pos in open_positions:
            pnl_pct = pos.unrealized_pnl_pct
            current_price = pos.current_price_usd

            # A. Check Hard Stop-Loss
            if pnl_pct <= self.config.stop_loss_pct:
                realized_pnl = self.executor.execute_sell(
                    position=pos,
                    sell_pct=100.0,
                    current_price=current_price,
                    reason=f"Stop-Loss breached: {pnl_pct:.2f}% <= {self.config.stop_loss_pct:.1f}%",
                )
                self.risk_manager.record_closed_trade_pnl(realized_pnl)
                self.log_decision(
                    action="EXECUTE_SELL",
                    reason=f"STOP LOSS triggered at {pnl_pct:.2f}%",
                    details={"token": pos.token_symbol, "realized_pnl": realized_pnl},
                )
                self.notifier.notify_exit(
                    symbol=pos.token_symbol,
                    sell_pct=100.0,
                    pnl_usd=realized_pnl,
                    pnl_pct=pnl_pct,
                    reason=f"Stop-loss hit ({pnl_pct:.1f}%)",
                    mode=self.config.mode,
                )
                continue

            # B. Check Multi-Tier Take-Profit Levels
            # Sort TP levels ascending by trigger_pct
            sorted_tp = sorted(enumerate(self.config.take_profit_levels), key=lambda x: x[1].trigger_pct)
            for idx, tp_level in sorted_tp:
                if pnl_pct >= tp_level.trigger_pct and idx not in pos.tp_levels_executed:
                    # Execute partial or full take-profit
                    pos.tp_levels_executed.append(idx)
                    realized_pnl = self.executor.execute_sell(
                        position=pos,
                        sell_pct=tp_level.sell_pct,
                        current_price=current_price,
                        reason=f"Take-Profit Tier #{idx+1} hit: +{pnl_pct:.1f}% >= +{tp_level.trigger_pct:.1f}%",
                    )
                    self.risk_manager.record_closed_trade_pnl(realized_pnl)
                    self.log_decision(
                        action="EXECUTE_SELL",
                        reason=f"TAKE PROFIT tier #{idx+1} ({tp_level.sell_pct}% sold)",
                        details={"token": pos.token_symbol, "pnl_pct": pnl_pct, "realized_pnl": realized_pnl},
                    )
                    self.notifier.notify_exit(
                        symbol=pos.token_symbol,
                        sell_pct=tp_level.sell_pct,
                        pnl_usd=realized_pnl,
                        pnl_pct=pnl_pct,
                        reason=f"Take-Profit Tier #{idx+1} (+{tp_level.trigger_pct:.0f}%)",
                        mode=self.config.mode,
                    )
                    break  # Execute one TP step per cycle to avoid cascading multi-fills on the same tick

    def process_new_events(self, events: List[SwapEvent]):
        """Processes incoming swap events from followed traders."""
        for event in events:
            # Check mirror sells if enabled
            if event.side == "SELL":
                if self.config.mirror_sells:
                    # Find open position in this token
                    matching = [p for p in self.executor.get_open_positions() if p.token_mint == event.token_mint]
                    for pos in matching:
                        realized_pnl = self.executor.execute_sell(
                            pos, sell_pct=100.0, current_price=event.price_usd, reason="Mirrored trader sell"
                        )
                        self.risk_manager.record_closed_trade_pnl(realized_pnl)
                        self.log_decision(
                            "EXECUTE_SELL", "Mirrored trader sell", {"token": pos.token_symbol, "trader": event.trader_address}
                        )
                else:
                    self.log_decision(
                        "SKIP", "Trader SELL ignored (mirror_sells=false)", {"token": event.token_symbol}
                    )
                continue

            # Event is a BUY
            current_market_price = self.stalkchain.get_token_price(event.token_mint) or event.price_usd

            # 1. Filter Engine Check
            passed_filter, filter_reason = self.filter_engine.evaluate_entry(event, current_market_price)
            if not passed_filter:
                self.log_decision(
                    "SKIP", f"Filter check failed: {filter_reason}",
                    {"token": event.token_symbol, "trader": event.trader_address[:8]}
                )
                continue

            # 2. Risk Manager Check
            open_positions = self.executor.get_open_positions()
            cash = self.executor.get_cash_balance()
            total_portfolio = self.executor.get_total_portfolio_value()

            can_open, risk_reason, approved_size = self.risk_manager.can_open_position(
                current_open_positions=len(open_positions),
                cash_balance_usd=cash,
                total_portfolio_usd=total_portfolio,
            )

            if not can_open:
                self.log_decision(
                    "SKIP", f"Risk check failed: {risk_reason}",
                    {"token": event.token_symbol, "cash": cash, "open_positions": len(open_positions)}
                )
                # Check if it was a circuit breaker
                if "breached" in risk_reason or "Kill switch" in risk_reason:
                    self.notifier.notify_risk_alert("Risk Limit Triggered", risk_reason)
                continue

            # 3. Execute Copy Order
            position = self.executor.execute_buy(
                token_mint=event.token_mint,
                token_symbol=event.token_symbol,
                usd_size=approved_size,
                current_price=current_market_price,
                copied_trader=event.trader_address,
            )

            if position:
                self.filter_engine.record_buy_execution(event.token_mint, event.trader_address)
                self.log_decision(
                    "EXECUTE_BUY",
                    f"Copied trader {event.trader_address[:8]}",
                    {"token": event.token_symbol, "size_usd": approved_size, "price": current_market_price}
                )
                self.notifier.notify_entry(
                    symbol=event.token_symbol,
                    mint=event.token_mint,
                    size_usd=approved_size,
                    price_usd=current_market_price,
                    trader=event.trader_address,
                    mode=self.config.mode,
                )

    def tick(self):
        """Single execution tick called periodically."""
        # 1. Evaluate open position exits (TP/SL)
        self.check_exits()

        # 2. Poll for new trader swaps
        new_events = self.stalkchain.poll_new_swaps(
            trader_addresses=self.config.followed_traders,
            since_ts=self.last_poll_ts,
        )
        self.last_poll_ts = int(time.time())

        # 3. Process new events
        if new_events:
            self.process_new_events(new_events)

    def get_status(self) -> BotStatus:
        """Returns comprehensive real-time status snapshot."""
        cash = self.executor.get_cash_balance()
        total_val = self.executor.get_total_portfolio_value()
        self.risk_manager.update_portfolio_peak(total_val)
        open_pos = self.executor.get_open_positions()

        unrealized_pnl = sum(p.unrealized_pnl_usd for p in open_pos)
        daily_loss = self.risk_manager.get_daily_realized_loss_usd()
        drawdown_pct = self.risk_manager.get_current_drawdown_pct(total_val)

        return BotStatus(
            mode=self.config.mode,
            is_paused=self.risk_manager.kill_switch_triggered,
            kill_switch_active=self.risk_manager.kill_switch_triggered,
            starting_balance_usd=self.risk_manager.starting_balance_usd,
            cash_balance_usd=round(cash, 2),
            total_portfolio_usd=round(total_val, 2),
            peak_portfolio_usd=round(self.risk_manager.peak_portfolio_usd, 2),
            realized_pnl_usd=round(sum(t["pnl_usd"] for t in self.risk_manager.trade_pnl_history), 2),
            unrealized_pnl_usd=round(unrealized_pnl, 2),
            daily_realized_pnl_usd=round(-daily_loss, 2),
            current_drawdown_pct=round(drawdown_pct, 2),
            open_positions_count=len(open_pos),
            followed_traders=self.config.followed_traders,
            last_update_ts=int(time.time()),
        )
