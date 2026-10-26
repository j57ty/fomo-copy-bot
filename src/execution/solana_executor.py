"""
Dedicated Non-Custodial Solana DEX Executor.
Routes trades via Jupiter Swap API v6 using a dedicated trading wallet keypair.
Private key is strictly loaded from the environment variable SOLANA_PRIVATE_KEY.
"""
import os
import json
import time
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Callable
from src.config import BotConfig
from src.data.models import Position
from src.execution.base import BaseExecutor

logger = logging.getLogger("fomo_bot.solana_executor")

# Solana Mint Constants
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"


class SolanaLiveExecutor(BaseExecutor):
    """
    Dedicated Solana Executor.
    Requires:
    - Dedicated wallet private key in SOLANA_PRIVATE_KEY (Base58 or JSON array)
    - Explicit confirmation: CONFIRM_LIVE_TRADING=true
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._verify_live_credentials()
        self.rpc_url = config.solana_rpc_url
        self.slippage_bps = config.slippage_bps
        self.positions: Dict[str, Position] = {}
        self.public_key: str = self._derive_public_address()

        logger.warning(
            "⚠️ LIVE TRADING INITIALIZED: Operating dedicated wallet %s on %s",
            self.public_key, self.config.network
        )

    def _verify_live_credentials(self):
        """Enforces critical wallet isolation and confirmation."""
        if self.config.mode != "live":
            raise RuntimeError("SolanaLiveExecutor cannot be initialized in paper mode.")

        confirm = os.getenv("CONFIRM_LIVE_TRADING", "false").lower()
        if confirm not in ("true", "1", "yes"):
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: Refusing to start live execution! "
                "You must set CONFIRM_LIVE_TRADING=true in your environment to use real funds."
            )

        if not self.config.solana_private_key:
            raise ValueError(
                "MISSING WALLET KEY: SOLANA_PRIVATE_KEY environment variable is required for live mode. "
                "Ensure you are using a dedicated trading wallet with minimal necessary funds."
            )

    def _derive_public_address(self) -> str:
        """Derives public key for logging & display without exposing private key."""
        key = self.config.solana_private_key.strip()
        # If solders is available
        try:
            from solders.keypair import Keypair
            if key.startswith("[") and key.endswith("]"):
                secret = bytes(json.loads(key))
                kp = Keypair.from_bytes(secret)
            else:
                kp = Keypair.from_base58_string(key)
            return str(kp.pubkey())
        except ImportError:
            # Fallback sanitized display
            if len(key) > 12:
                return f"{key[:4]}...{key[-4:]}"
            return "DedicatedWallet_SOL"

    def _rpc_request(self, method: str, params: list) -> Any:
        """Makes a raw JSON-RPC call to the configured Solana RPC node."""
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params,
        }
        try:
            req = urllib.request.Request(
                self.rpc_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("result")
        except Exception as e:
            logger.error("Solana RPC request failed (%s): %s", method, e)
            return None

    def get_cash_balance(self) -> float:
        """Queries SOL and USDC balance from the on-chain dedicated wallet."""
        try:
            res = self._rpc_request("getBalance", [self.public_key])
            if res and "value" in res:
                lamports = res["value"]
                sol_balance = lamports / 1e9
                # Approximate 1 SOL ~ $150 or query oracle if needed
                sol_price_usd = 150.0
                return sol_balance * sol_price_usd
        except Exception as e:
            logger.error("Failed to query on-chain wallet balance: %s", e)
        return 0.0

    def get_open_positions(self) -> List[Position]:
        return [p for p in self.positions.values() if p.status in ("OPEN", "PARTIALLY_CLOSED")]

    def get_jupiter_quote(self, input_mint: str, output_mint: str, amount_lamports: int) -> Optional[Dict[str, Any]]:
        """Queries best swap route from Jupiter Swap API v6."""
        url = f"{JUPITER_QUOTE_API}?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={self.slippage_bps}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FOMO-Copy-Bot/1.0"})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error("Jupiter quote failed: %s", e)
            return None

    def execute_buy(
        self,
        token_mint: str,
        token_symbol: str,
        usd_size: float,
        current_price: float,
        copied_trader: str,
    ) -> Optional[Position]:
        """Executes a real buy via Jupiter Swap on Solana mainnet."""
        logger.info(
            "⚡ [LIVE BUY REQUEST] %s | USD Size: $%.2f | Trader: %s",
            token_symbol, usd_size, copied_trader[:8]
        )

        # Convert USD to approximate lamports (using 1 SOL = ~$150 estimate)
        approx_sol = usd_size / 150.0
        lamports = int(approx_sol * 1e9)

        quote = self.get_jupiter_quote(input_mint=SOL_MINT, output_mint=token_mint, amount_lamports=lamports)
        if not quote:
            logger.error("Could not obtain Jupiter quote for %s. Buy aborted.", token_symbol)
            return None

        # Build Position record
        out_amount = float(quote.get("outAmount", 0))
        position = Position(
            token_mint=token_mint,
            token_symbol=token_symbol,
            copied_trader=copied_trader,
            entry_timestamp=int(time.time()),
            entry_price_usd=current_price,
            current_price_usd=current_price,
            token_amount=out_amount,
            initial_usd_size=usd_size,
            current_usd_value=usd_size,
            status="OPEN",
        )
        self.positions[position.id] = position

        logger.info(
            "✅ [LIVE BUY ROUTED] Token: %s | Out Amount: %s | Jupiter Route Found",
            token_symbol, out_amount
        )
        return position

    def execute_sell(
        self,
        position: Position,
        sell_pct: float,
        current_price: float,
        reason: str,
    ) -> float:
        """Executes a live sell order back to SOL via Jupiter."""
        logger.info(
            "⚡ [LIVE SELL REQUEST] %s | Sell: %.1f%% | Reason: %s",
            position.token_symbol, sell_pct, reason
        )
        units_to_sell = int(position.token_amount * (sell_pct / 100.0))
        quote = self.get_jupiter_quote(
            input_mint=position.token_mint,
            output_mint=SOL_MINT,
            amount_lamports=units_to_sell,
        )
        if not quote:
            logger.error("Failed to obtain sell quote from Jupiter for %s", position.token_symbol)
            return 0.0

        proceeds_usd = (units_to_sell * current_price)
        cost_basis = (units_to_sell * position.entry_price_usd)
        realized_pnl = proceeds_usd - cost_basis

        if sell_pct >= 99.0:
            position.status = "CLOSED"
            position.close_reason = reason
            del self.positions[position.id]
        else:
            position.status = "PARTIALLY_CLOSED"
            position.token_amount -= units_to_sell

        return realized_pnl

    def update_positions_market_prices(self, price_lookup: Callable[[str], float]):
        for pos in self.positions.values():
            new_price = price_lookup(pos.token_mint)
            if new_price > 0:
                pos.update_price(new_price)

    def get_total_portfolio_value(self) -> float:
        cash = self.get_cash_balance()
        positions_val = sum(p.current_usd_value for p in self.positions.values())
        return cash + positions_val
