"""
StalkChain MCP Client for querying FOMO (fomo.family) on-chain trader analytics.
Connects to https://data.stalkchain.com/mcp via JSON-RPC / MCP tools.
"""
import json
import logging
import time
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from src.data.models import Trader, SwapEvent, TokenInfo
from src.data.mock_data import MockStalkChainData

logger = logging.getLogger("fomo_bot.stalkchain")


class StalkChainClient:
    """
    Client for interacting with the StalkChain MCP server.
    Implements standard MCP tool execution:
    - stalkchain_fomo_leaderboard
    - stalkchain_fomo_resolve_trader
    - stalkchain_fomo_trader_balances
    - stalkchain_fomo_trader_positions
    - stalkchain_fomo_trader_swaps
    """

    def __init__(self, mcp_url: str = "https://data.stalkchain.com/mcp", api_key: str = "", use_mock_fallback: bool = True):
        self.mcp_url = mcp_url
        self.api_key = api_key
        self.use_mock_fallback = use_mock_fallback
        self.mock_data = MockStalkChainData()
        self._last_polled_txs: set = set()

    def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Executes an MCP tool call over HTTP JSON-RPC to the StalkChain MCP endpoint."""
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FOMO-Copy-Bot/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            req = urllib.request.Request(
                self.mcp_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                if "error" in res_json:
                    logger.warning("StalkChain MCP returned error for %s: %s", tool_name, res_json["error"])
                    return None
                return res_json.get("result")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception) as exc:
            logger.debug("StalkChain MCP network call failed (%s): %s", tool_name, exc)
            return None

    def get_fomo_leaderboard(self, timeframe: str = "7d", limit: int = 10) -> List[Trader]:
        """
        Queries top profitable FOMO traders ranked by PnL.
        Supported timeframes: '24h', '7d', '30d', 'all_time'.
        """
        res = self._call_mcp_tool("stalkchain_fomo_leaderboard", {"timeframe": timeframe, "limit": limit})
        if res and "content" in res:
            try:
                # Parse MCP response content
                content_text = res["content"][0].get("text", "[]") if isinstance(res["content"], list) else str(res["content"])
                traders_raw = json.loads(content_text)
                traders = []
                for idx, t in enumerate(traders_raw, 1):
                    traders.append(Trader(
                        address=t.get("address", ""),
                        handle=t.get("handle", f"trader_{t.get('address', '')[:6]}"),
                        pnl_usd=float(t.get("pnl_usd", 0.0)),
                        pnl_pct=float(t.get("pnl_pct", 0.0)),
                        win_rate=float(t.get("win_rate", 0.0)),
                        trade_count=int(t.get("trade_count", 0)),
                        timeframe=timeframe,
                        chain=t.get("chain", "solana"),
                        followers=int(t.get("followers", 0)),
                        rank=idx,
                    ))
                return traders
            except Exception as e:
                logger.warning("Failed to parse MCP leaderboard payload: %s", e)

        if self.use_mock_fallback:
            return self.mock_data.get_leaderboard(timeframe=timeframe, limit=limit)
        return []

    def resolve_trader(self, address_or_handle: str) -> Optional[Trader]:
        """Resolves trader profile details and metrics."""
        res = self._call_mcp_tool("stalkchain_fomo_resolve_trader", {"identifier": address_or_handle})
        if res and "content" in res:
            try:
                content_text = res["content"][0].get("text", "{}")
                data = json.loads(content_text)
                return Trader(
                    address=data.get("address", address_or_handle),
                    handle=data.get("handle", address_or_handle[:8]),
                    pnl_usd=float(data.get("pnl_usd", 0.0)),
                    pnl_pct=float(data.get("pnl_pct", 0.0)),
                    win_rate=float(data.get("win_rate", 0.0)),
                    trade_count=int(data.get("trade_count", 0)),
                    followers=int(data.get("followers", 0)),
                )
            except Exception as e:
                logger.warning("Failed to parse resolve trader response: %s", e)

        if self.use_mock_fallback:
            return self.mock_data.resolve_trader(address_or_handle)
        return None

    def get_trader_swaps(self, trader_address: str, limit: int = 15) -> List[SwapEvent]:
        """Fetches recent fills and swap executions for a trader."""
        res = self._call_mcp_tool("stalkchain_fomo_trader_swaps", {"address": trader_address, "limit": limit})
        if res and "content" in res:
            try:
                content_text = res["content"][0].get("text", "[]")
                swaps_raw = json.loads(content_text)
                events = []
                for s in swaps_raw:
                    events.append(SwapEvent(
                        tx_hash=s.get("tx_hash", ""),
                        timestamp=int(s.get("timestamp", time.time())),
                        trader_address=trader_address,
                        side=s.get("side", "BUY").upper(),
                        token_mint=s.get("token_mint", ""),
                        token_symbol=s.get("token_symbol", "TOKEN"),
                        amount_token=float(s.get("amount_token", 0.0)),
                        amount_usd=float(s.get("amount_usd", 0.0)),
                        price_usd=float(s.get("price_usd", 0.0)),
                        chain=s.get("chain", "solana"),
                        is_first_buy=bool(s.get("is_first_buy", False)),
                        liquidity_usd=float(s.get("liquidity_usd", 50000.0)),
                        market_cap_usd=float(s.get("market_cap_usd", 1000000.0)),
                    ))
                return events
            except Exception as e:
                logger.warning("Failed to parse trader swaps: %s", e)

        if self.use_mock_fallback:
            return self.mock_data.get_trader_swaps(trader_address, limit=limit)
        return []

    def get_token_price(self, token_mint: str) -> float:
        """Pulls latest token price in USD."""
        res = self._call_mcp_tool("stalkchain_token_price", {"mint": token_mint})
        if res and "content" in res:
            try:
                content_text = res["content"][0].get("text", "{}")
                data = json.loads(content_text)
                return float(data.get("price_usd", 0.0))
            except Exception:
                pass

        if self.use_mock_fallback:
            return self.mock_data.get_token_price(token_mint)
        return 0.0

    def poll_new_swaps(self, trader_addresses: List[str], since_ts: int = 0) -> List[SwapEvent]:
        """Polls for new swap executions across followed traders."""
        new_swaps: List[SwapEvent] = []
        for address in trader_addresses:
            swaps = self.get_trader_swaps(address, limit=5)
            for s in swaps:
                if s.tx_hash not in self._last_polled_txs and s.timestamp >= since_ts:
                    self._last_polled_txs.add(s.tx_hash)
                    new_swaps.append(s)

        # Cap stored history to avoid memory leak
        if len(self._last_polled_txs) > 5000:
            self._last_polled_txs = set(list(self._last_polled_txs)[-2000:])

        return new_swaps
