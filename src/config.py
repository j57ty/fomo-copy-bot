"""
Configuration loader with environment variable overrides and safety validation.
"""
import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from src.data.models import TakeProfitLevel

logger = logging.getLogger("fomo_bot.config")


@dataclass
class TakeProfitConfig:
    trigger_pct: float
    sell_pct: float


@dataclass
class BotConfig:
    # Bot Core
    mode: str = "paper"  # "paper" or "live"
    bot_name: str = "FOMO Copy Bot"
    poll_interval_seconds: int = 5

    # StalkChain MCP Data Source
    stalkchain_mcp_url: str = "https://data.stalkchain.com/mcp"
    stalkchain_api_key: str = ""
    leaderboard_timeframe: str = "7d"  # 24h, 7d, 30d, all_time
    auto_sync_top_traders: bool = False
    top_traders_count: int = 5

    # Trader Addresses to Follow
    followed_traders: List[str] = field(default_factory=list)

    # Trading Execution Parameters
    size_mode: str = "fixed"  # "fixed" or "percent"
    trade_size_usd: float = 50.0
    portfolio_pct_per_trade: float = 5.0
    max_open_positions: int = 5
    max_chase_pct: float = 5.0
    copy_first_buy_only: bool = True
    token_cooldown_seconds: int = 600
    mirror_sells: bool = False

    # Token Safety & Quality Filters
    min_liquidity_usd: float = 25000.0
    min_market_cap_usd: float = 50000.0
    max_market_cap_usd: float = 50000000.0

    # Exit Rules
    take_profit_levels: List[TakeProfitConfig] = field(default_factory=lambda: [
        TakeProfitConfig(trigger_pct=100.0, sell_pct=50.0),   # 2x: sell 50%
        TakeProfitConfig(trigger_pct=300.0, sell_pct=25.0),   # 4x: sell 25%
        TakeProfitConfig(trigger_pct=500.0, sell_pct=100.0),  # 6x: sell remaining
    ])
    stop_loss_pct: float = -35.0

    # Hard Risk Limits
    max_daily_loss_usd: float = 200.0
    max_portfolio_drawdown_pct: float = 25.0
    kill_switch_active: bool = False

    # Wallet & Network
    network: str = "solana"
    starting_paper_balance_usd: float = 1000.0
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_private_key: str = ""
    slippage_bps: int = 150  # 1.5%

    # Notifications
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_on_entry: bool = True
    notify_on_exit: bool = True
    notify_on_risk_alert: bool = True

    # Web Dashboard / Health Check
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    def validate_safety(self):
        """Strict validation of safety guards before bot execution."""
        if self.mode == "live":
            confirm = os.getenv("CONFIRM_LIVE_TRADING", "false").lower()
            if confirm not in ("true", "1", "yes"):
                raise ValueError(
                    "SAFETY HALT: Mode is set to 'live', but CONFIRM_LIVE_TRADING=true is NOT set in environment! "
                    "Bot will refuse to run in live mode without explicit confirmation."
                )
            if not self.solana_private_key:
                raise ValueError(
                    "SAFETY HALT: Live trading requires SOLANA_PRIVATE_KEY environment variable. "
                    "Never commit private keys to code or files."
                )
        if self.stop_loss_pct >= 0:
            raise ValueError(f"stop_loss_pct must be negative (e.g. -35.0), got {self.stop_loss_pct}")
        if self.max_daily_loss_usd <= 0:
            raise ValueError("max_daily_loss_usd must be greater than 0")
        if not (0 < self.max_portfolio_drawdown_pct < 100):
            raise ValueError("max_portfolio_drawdown_pct must be between 0 and 100")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be at least 1")


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Lightweight pure-python YAML parser supporting sections, lists, and list of dicts."""
    result: Dict[str, Any] = {}
    lines = text.splitlines()

    current_section: Optional[str] = None
    current_list_key: Optional[str] = None
    current_dict_item: Optional[Dict[str, Any]] = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Top-level section (indent 0)
        if indent == 0 and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.split("#")[0].strip()
            if not val:
                current_section = key
                result[current_section] = {}
                current_list_key = None
                current_dict_item = None
            else:
                current_section = None
                result[key] = _cast_scalar(val)
                current_list_key = None
                current_dict_item = None
            continue

        # Sub-level elements (indent > 0)
        if current_section is not None:
            # Handle list item: '- ...'
            if stripped.startswith("-"):
                item_content = stripped[1:].strip()
                # Check if it's a key-value in a list of dicts: '- key: val'
                if ":" in item_content:
                    sub_k, sub_v = item_content.split(":", 1)
                    sub_k = sub_k.strip()
                    sub_v = sub_v.split("#")[0].strip()
                    new_item = {sub_k: _cast_scalar(sub_v)}
                    current_dict_item = new_item

                    target_list_name = current_list_key
                    if target_list_name:
                        if not isinstance(result[current_section].get(target_list_name), list):
                            result[current_section][target_list_name] = []
                        result[current_section][target_list_name].append(new_item)
                    else:
                        if not isinstance(result[current_section], list):
                            result[current_section] = []
                        result[current_section].append(new_item)
                else:
                    # Simple list scalar item: '- "addr"'
                    scalar_val = _cast_scalar(item_content)
                    current_dict_item = None
                    target_list_name = current_list_key
                    if target_list_name:
                        if not isinstance(result[current_section].get(target_list_name), list):
                            result[current_section][target_list_name] = []
                        result[current_section][target_list_name].append(scalar_val)
                    else:
                        if not isinstance(result[current_section], list):
                            result[current_section] = []
                        result[current_section].append(scalar_val)
                continue

            # Handle continuation of a dict item in a list (e.g. sell_pct: 50.0 under - trigger_pct: 100.0)
            if current_dict_item is not None and indent >= 4 and ":" in stripped:
                sub_k, sub_v = stripped.split(":", 1)
                sub_k = sub_k.strip()
                sub_v = sub_v.split("#")[0].strip()
                current_dict_item[sub_k] = _cast_scalar(sub_v)
                continue

            # Reset dict item if indent decreased
            current_dict_item = None

            # Handle standard sub-keys: 'key: val' or 'key:'
            if ":" in stripped:
                sub_k, sub_v = stripped.split(":", 1)
                sub_k = sub_k.strip()
                sub_v = sub_v.split("#")[0].strip()
                if not sub_v:
                    # Header for a list or sub-dict
                    current_list_key = sub_k
                    result[current_section][current_list_key] = []
                else:
                    current_list_key = None
                    if isinstance(result[current_section], dict):
                        result[current_section][sub_k] = _cast_scalar(sub_v)

    return result


def _cast_scalar(val: str) -> Any:
    val = val.split("#")[0].strip()
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val.lower() in ("null", "none", "~", ""):
        return None
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def load_config(config_path: Optional[str] = None) -> BotConfig:
    """Loads configuration from YAML/JSON file with environment variable overrides."""
    data: Dict[str, Any] = {}

    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
            try:
                import yaml
                data = yaml.safe_load(content) or {}
            except ImportError:
                data = _parse_simple_yaml(content)
            logger.info("Loaded configuration from %s", config_path)
    else:
        # Check standard paths
        default_paths = ["config/config.yaml", "config/config.json", "config/config_example.yaml"]
        for p in default_paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                    try:
                        import yaml
                        data = yaml.safe_load(content) or {}
                    except ImportError:
                        data = _parse_simple_yaml(content)
                logger.info("Loaded configuration from default path %s", p)
                break

    bot_cfg = BotConfig()

    # Bot core
    if "bot" in data:
        b = data["bot"]
        bot_cfg.mode = b.get("mode", bot_cfg.mode)
        bot_cfg.bot_name = b.get("name", bot_cfg.bot_name)
        bot_cfg.poll_interval_seconds = int(b.get("poll_interval_seconds", bot_cfg.poll_interval_seconds))

    # StalkChain
    if "stalkchain" in data:
        sc = data["stalkchain"]
        bot_cfg.stalkchain_mcp_url = sc.get("mcp_url", bot_cfg.stalkchain_mcp_url)
        bot_cfg.stalkchain_api_key = sc.get("api_key", bot_cfg.stalkchain_api_key)
        bot_cfg.leaderboard_timeframe = sc.get("leaderboard_timeframe", bot_cfg.leaderboard_timeframe)
        bot_cfg.auto_sync_top_traders = bool(sc.get("auto_sync_top_traders", bot_cfg.auto_sync_top_traders))
        bot_cfg.top_traders_count = int(sc.get("top_traders_count", bot_cfg.top_traders_count))

    # Traders
    if "traders" in data and isinstance(data["traders"], list):
        bot_cfg.followed_traders = [str(t) for t in data["traders"]]

    # Trading parameters
    if "trading" in data:
        t = data["trading"]
        bot_cfg.size_mode = t.get("size_mode", bot_cfg.size_mode)
        bot_cfg.trade_size_usd = float(t.get("trade_size_usd", bot_cfg.trade_size_usd))
        bot_cfg.portfolio_pct_per_trade = float(t.get("portfolio_pct_per_trade", bot_cfg.portfolio_pct_per_trade))
        bot_cfg.max_open_positions = int(t.get("max_open_positions", bot_cfg.max_open_positions))
        bot_cfg.max_chase_pct = float(t.get("max_chase_pct", bot_cfg.max_chase_pct))
        bot_cfg.copy_first_buy_only = bool(t.get("copy_first_buy_only", bot_cfg.copy_first_buy_only))
        bot_cfg.token_cooldown_seconds = int(t.get("token_cooldown_seconds", bot_cfg.token_cooldown_seconds))
        bot_cfg.mirror_sells = bool(t.get("mirror_sells", bot_cfg.mirror_sells))

    # Filters
    if "filters" in data:
        f = data["filters"]
        bot_cfg.min_liquidity_usd = float(f.get("min_liquidity_usd", bot_cfg.min_liquidity_usd))
        bot_cfg.min_market_cap_usd = float(f.get("min_market_cap_usd", bot_cfg.min_market_cap_usd))
        bot_cfg.max_market_cap_usd = float(f.get("max_market_cap_usd", bot_cfg.max_market_cap_usd))

    # Exits
    if "exits" in data:
        ex = data["exits"]
        bot_cfg.stop_loss_pct = float(ex.get("stop_loss_pct", bot_cfg.stop_loss_pct))
        if "take_profit_levels" in ex and isinstance(ex["take_profit_levels"], list):
            tp_list = []
            for item in ex["take_profit_levels"]:
                if isinstance(item, dict):
                    tp_list.append(TakeProfitConfig(
                        trigger_pct=float(item.get("trigger_pct", 100.0)),
                        sell_pct=float(item.get("sell_pct", 50.0))
                    ))
            if tp_list:
                bot_cfg.take_profit_levels = tp_list

    # Safety
    if "safety" in data:
        s = data["safety"]
        bot_cfg.max_daily_loss_usd = float(s.get("max_daily_loss_usd", bot_cfg.max_daily_loss_usd))
        bot_cfg.max_portfolio_drawdown_pct = float(s.get("max_portfolio_drawdown_pct", bot_cfg.max_portfolio_drawdown_pct))
        bot_cfg.kill_switch_active = bool(s.get("kill_switch", bot_cfg.kill_switch_active))

    # Wallet
    if "wallet" in data:
        w = data["wallet"]
        bot_cfg.network = w.get("network", bot_cfg.network)
        bot_cfg.starting_paper_balance_usd = float(w.get("starting_paper_balance_usd", bot_cfg.starting_paper_balance_usd))
        bot_cfg.solana_rpc_url = w.get("solana_rpc_url", bot_cfg.solana_rpc_url)
        bot_cfg.slippage_bps = int(w.get("slippage_bps", bot_cfg.slippage_bps))

    # Notifications
    if "notifications" in data:
        n = data["notifications"]
        bot_cfg.telegram_enabled = bool(n.get("telegram_enabled", bot_cfg.telegram_enabled))
        bot_cfg.telegram_bot_token = str(n.get("telegram_bot_token", bot_cfg.telegram_bot_token))
        bot_cfg.telegram_chat_id = str(n.get("telegram_chat_id", bot_cfg.telegram_chat_id))
        bot_cfg.notify_on_entry = bool(n.get("notify_on_entry", bot_cfg.notify_on_entry))
        bot_cfg.notify_on_exit = bool(n.get("notify_on_exit", bot_cfg.notify_on_exit))
        bot_cfg.notify_on_risk_alert = bool(n.get("notify_on_risk_alert", bot_cfg.notify_on_risk_alert))

    # Web / Render Port
    if "web" in data:
        wb = data["web"]
        bot_cfg.web_host = str(wb.get("host", bot_cfg.web_host))
        bot_cfg.web_port = int(wb.get("port", bot_cfg.web_port))

    # Environment Variable Overrides (High Priority)
    bot_cfg.mode = os.getenv("BOT_MODE", bot_cfg.mode).lower()
    bot_cfg.solana_private_key = os.getenv("SOLANA_PRIVATE_KEY", bot_cfg.solana_private_key)
    bot_cfg.solana_rpc_url = os.getenv("SOLANA_RPC_URL", bot_cfg.solana_rpc_url)
    bot_cfg.stalkchain_api_key = os.getenv("STALKCHAIN_API_KEY", bot_cfg.stalkchain_api_key)
    bot_cfg.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", bot_cfg.telegram_bot_token)
    bot_cfg.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", bot_cfg.telegram_chat_id)
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        bot_cfg.telegram_enabled = True

    if os.getenv("PORT"):
        bot_cfg.web_port = int(os.getenv("PORT", "8080"))

    if os.getenv("KILL_SWITCH"):
        bot_cfg.kill_switch_active = os.getenv("KILL_SWITCH", "").lower() in ("true", "1", "yes")

    if os.getenv("FOLLOWED_TRADERS"):
        bot_cfg.followed_traders = [t.strip() for t in os.getenv("FOLLOWED_TRADERS", "").split(",") if t.strip()]

    bot_cfg.validate_safety()
    return bot_cfg
