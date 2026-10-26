"""
Paper Trading Simulation Executor.
Provides high-fidelity simulated fills with realistic slippage, position management,
and SQLite persistence so balances and trade history survive process restarts.
"""
import os
import time
import sqlite3
import logging
from typing import List, Dict, Optional, Callable
from src.data.models import Position
from src.execution.base import BaseExecutor

logger = logging.getLogger("fomo_bot.paper_executor")


class PaperExecutor(BaseExecutor):

    def __init__(
        self,
        starting_balance_usd: float = 1000.0,
        slippage_bps: int = 150,
        db_path: str = "paper_trading.db",
    ):
        self.starting_balance_usd = starting_balance_usd
        self.slippage_rate = slippage_bps / 10000.0  # 150 bps = 0.015 (1.5%)
        self.db_path = db_path
        
        self.cash_balance_usd: float = starting_balance_usd
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []

        self._init_db()
        self._load_state()

    def _init_db(self):
        """Initializes SQLite schema for paper trading."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS paper_state (
                        id INTEGER PRIMARY KEY,
                        cash_balance REAL,
                        updated_at INTEGER
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        id TEXT PRIMARY KEY,
                        token_mint TEXT,
                        token_symbol TEXT,
                        copied_trader TEXT,
                        entry_timestamp INTEGER,
                        entry_price_usd REAL,
                        current_price_usd REAL,
                        token_amount REAL,
                        initial_usd_size REAL,
                        current_usd_value REAL,
                        unrealized_pnl_usd REAL,
                        unrealized_pnl_pct REAL,
                        realized_pnl_usd REAL,
                        tp_levels_executed TEXT,
                        status TEXT,
                        close_reason TEXT,
                        close_timestamp INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Could not initialize SQLite persistence: %s. Running in-memory.", e)

    def _load_state(self):
        """Loads persistent cash balance and open positions from SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cash_balance FROM paper_state WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    self.cash_balance_usd = row[0]
                else:
                    cursor.execute(
                        "INSERT INTO paper_state (id, cash_balance, updated_at) VALUES (1, ?, ?)",
                        (self.cash_balance_usd, int(time.time())),
                    )
                    conn.commit()

                # Load open positions
                cursor.execute("SELECT * FROM positions WHERE status IN ('OPEN', 'PARTIALLY_CLOSED')")
                for r in cursor.fetchall():
                    # r: (id, token_mint, token_symbol, copied_trader, entry_timestamp, entry_price_usd,
                    #     current_price_usd, token_amount, initial_usd_size, current_usd_value,
                    #     unrealized_pnl_usd, unrealized_pnl_pct, realized_pnl_usd, tp_levels_executed,
                    #     status, close_reason, close_timestamp)
                    tp_levels = [int(x) for x in r[13].split(",") if x.strip()] if r[13] else []
                    pos = Position(
                        id=r[0],
                        token_mint=r[1],
                        token_symbol=r[2],
                        copied_trader=r[3],
                        entry_timestamp=r[4],
                        entry_price_usd=r[5],
                        current_price_usd=r[6],
                        token_amount=r[7],
                        initial_usd_size=r[8],
                        current_usd_value=r[9],
                        unrealized_pnl_usd=r[10],
                        unrealized_pnl_pct=r[11],
                        realized_pnl_usd=r[12],
                        tp_levels_executed=tp_levels,
                        status=r[14],
                        close_reason=r[15],
                        close_timestamp=r[16],
                    )
                    self.positions[pos.id] = pos
        except Exception as e:
            logger.debug("Failed loading persistent paper state: %s", e)

    def _save_state(self):
        """Saves current state to SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE paper_state SET cash_balance = ?, updated_at = ? WHERE id = 1",
                    (self.cash_balance_usd, int(time.time())),
                )
                for pos in list(self.positions.values()) + self.closed_positions[-50:]:
                    tp_str = ",".join(str(x) for x in pos.tp_levels_executed)
                    cursor.execute("""
                        INSERT OR REPLACE INTO positions (
                            id, token_mint, token_symbol, copied_trader, entry_timestamp,
                            entry_price_usd, current_price_usd, token_amount, initial_usd_size,
                            current_usd_value, unrealized_pnl_usd, unrealized_pnl_pct,
                            realized_pnl_usd, tp_levels_executed, status, close_reason, close_timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pos.id, pos.token_mint, pos.token_symbol, pos.copied_trader, pos.entry_timestamp,
                        pos.entry_price_usd, pos.current_price_usd, pos.token_amount, pos.initial_usd_size,
                        pos.current_usd_value, pos.unrealized_pnl_usd, pos.unrealized_pnl_pct,
                        pos.realized_pnl_usd, tp_str, pos.status, pos.close_reason, pos.close_timestamp
                    ))
                conn.commit()
        except Exception as e:
            logger.debug("Failed saving persistent paper state: %s", e)

    def get_cash_balance(self) -> float:
        return self.cash_balance_usd

    def get_open_positions(self) -> List[Position]:
        return [p for p in self.positions.values() if p.status in ("OPEN", "PARTIALLY_CLOSED")]

    def execute_buy(
        self,
        token_mint: str,
        token_symbol: str,
        usd_size: float,
        current_price: float,
        copied_trader: str,
    ) -> Optional[Position]:
        """Simulates buying a token with slippage deduction."""
        if usd_size > self.cash_balance_usd:
            logger.warning("Paper buy rejected: usd_size $%.2f > cash $%.2f", usd_size, self.cash_balance_usd)
            return None

        # Simulate execution price with slippage (+1.5%)
        effective_price = current_price * (1.0 + self.slippage_rate)
        if effective_price <= 0:
            effective_price = 0.000001

        token_amount = usd_size / effective_price
        self.cash_balance_usd -= usd_size

        position = Position(
            token_mint=token_mint,
            token_symbol=token_symbol,
            copied_trader=copied_trader,
            entry_timestamp=int(time.time()),
            entry_price_usd=effective_price,
            current_price_usd=current_price,
            token_amount=token_amount,
            initial_usd_size=usd_size,
            current_usd_value=usd_size,
            unrealized_pnl_usd=0.0,
            unrealized_pnl_pct=0.0,
            realized_pnl_usd=0.0,
            status="OPEN",
        )

        self.positions[position.id] = position
        self._save_state()

        logger.info(
            "📝 [PAPER BUY] %s | Size: $%.2f | Tokens: %.4f | Price: $%.6f (slippage: %.2f%%) | Trader: %s",
            token_symbol, usd_size, token_amount, effective_price, self.slippage_rate * 100, copied_trader[:8]
        )
        return position

    def execute_sell(
        self,
        position: Position,
        sell_pct: float,
        current_price: float,
        reason: str,
    ) -> float:
        """Simulates selling a percentage of an open position."""
        if position.id not in self.positions:
            return 0.0

        sell_pct = min(100.0, max(1.0, sell_pct))
        units_to_sell = position.token_amount * (sell_pct / 100.0)

        # Simulate execution price with slippage (-1.5%)
        effective_price = current_price * (1.0 - self.slippage_rate)
        gross_proceeds = units_to_sell * effective_price
        cost_basis = units_to_sell * position.entry_price_usd
        realized_pnl = gross_proceeds - cost_basis

        # Update cash
        self.cash_balance_usd += gross_proceeds

        # Update position
        position.token_amount -= units_to_sell
        position.realized_pnl_usd += realized_pnl

        if sell_pct >= 99.9 or position.token_amount <= 0.00001:
            position.status = "CLOSED"
            position.close_reason = reason
            position.close_timestamp = int(time.time())
            position.token_amount = 0.0
            position.current_usd_value = 0.0
            del self.positions[position.id]
            self.closed_positions.append(position)
        else:
            position.status = "PARTIALLY_CLOSED"
            position.current_usd_value = position.token_amount * current_price

        self._save_state()

        logger.info(
            "📝 [PAPER SELL] %s | Sold: %.1f%% | Proceeds: $%.2f | Realized PnL: %+$%.2f | Reason: %s",
            position.token_symbol, sell_pct, gross_proceeds, realized_pnl, reason
        )
        return realized_pnl

    def update_positions_market_prices(self, price_lookup: Callable[[str], float]):
        """Updates prices and unrealized PnL across active positions."""
        for pos in self.positions.values():
            new_price = price_lookup(pos.token_mint)
            if new_price > 0:
                pos.update_price(new_price)
        self._save_state()

    def get_total_portfolio_value(self) -> float:
        open_value = sum(p.current_usd_value for p in self.positions.values())
        return self.cash_balance_usd + open_value
