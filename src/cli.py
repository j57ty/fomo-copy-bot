"""
Command Line Interface (CLI) for FOMO Copy-Trading Bot.
Provides instant controls: status, leaderboard, follow/unfollow, kill switch.
"""
import sys
import os
import argparse
import json

# Ensure UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import load_config
from src.data.stalkchain_mcp import StalkChainClient
from src.execution.paper_executor import PaperExecutor
from src.risk.risk_manager import RiskManager


def print_banner():
    print("""
=====================================================
   [FOMO COPY-TRADING BOT] (fomo.family / StalkChain)
=====================================================
""")


def cmd_status(args):
    config = load_config(args.config)
    executor = PaperExecutor(starting_balance_usd=config.starting_paper_balance_usd)
    risk = RiskManager(config, starting_balance_usd=executor.get_total_portfolio_value())

    cash = executor.get_cash_balance()
    portfolio = executor.get_total_portfolio_value()
    open_pos = executor.get_open_positions()
    daily_loss = risk.get_daily_realized_loss_usd()
    drawdown = risk.get_current_drawdown_pct(portfolio)

    print_banner()
    print(f"Mode:                   {config.mode.upper()}")
    print(f"Kill Switch Active:     {'[HALTED] YES (PAUSED)' if risk.check_kill_switch_file() or config.kill_switch_active else '[ACTIVE] NO'}")
    print(f"Total Portfolio Value:  ${portfolio:,.2f}")
    print(f"Cash Available:         ${cash:,.2f}")
    print(f"Rolling 24h Loss:       ${daily_loss:,.2f} (Limit: ${config.max_daily_loss_usd:,.2f})")
    print(f"Peak Drawdown:          {drawdown:.1f}% (Limit: {config.max_portfolio_drawdown_pct:.1f}%)")
    print(f"Open Positions:         {len(open_pos)} / {config.max_open_positions}")
    print(f"Followed Traders:       {len(config.followed_traders)}")
    for t in config.followed_traders:
        print(f"  • {t}")

    print("\n--- OPEN POSITIONS ---")
    if not open_pos:
        print("  (None)")
    for p in open_pos:
        pnl_sign = "+" if p.unrealized_pnl_pct >= 0 else ""
        print(f"  • {p.token_symbol:<8} | Entry: ${p.entry_price_usd:.6f} | Curr: ${p.current_price_usd:.6f} | Value: ${p.current_usd_value:.2f} | PnL: {pnl_sign}{p.unrealized_pnl_pct:.2f}%")


def cmd_traders(args):
    config = load_config(args.config)
    client = StalkChainClient(mcp_url=config.stalkchain_mcp_url, api_key=config.stalkchain_api_key)
    leaderboard = client.get_fomo_leaderboard(timeframe=args.timeframe, limit=args.limit)

    print_banner()
    print(f"Top Profitable FOMO Traders ({args.timeframe.upper()} StalkChain Leaderboard):")
    print(f"{'Rank':<6}{'Handle / Wallet':<32}{'PnL (USD)':<14}{'PnL (%)':<12}{'Win Rate':<10}{'Trades':<8}")
    print("-" * 82)
    for t in leaderboard:
        handle_display = f"@{t.handle}" if t.handle else t.address[:12]
        print(f"#{t.rank:<5}{handle_display:<32}${t.pnl_usd:>10,.0f}   {t.pnl_pct:>+8.1f}%   {t.win_rate:>6.1f}%   {t.trade_count:>6}")


def cmd_follow(args):
    config_path = args.config or "config/config.yaml"
    if not os.path.exists(config_path):
        print(f"Config file not found at {config_path}")
        return

    address = args.address.strip()
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    if address in content:
        print(f"Trader {address} is already in {config_path}")
        return

    # Append to traders section
    with open(config_path, "a", encoding="utf-8") as f:
        f.write(f'  - "{address}"\n')

    print(f"[OK] Added trader {address} to {config_path}")


def cmd_kill(args):
    with open(".killswitch", "w", encoding="utf-8") as f:
        f.write("Kill switch engaged via CLI\n")
    print("[HALT] EMERGENCY KILL SWITCH ENGAGED! All copying is paused immediately.")


def cmd_resume(args):
    for p in [".killswitch", "fomo-copy-bot/.killswitch"]:
        if os.path.exists(p):
            os.remove(p)
    print("[OK] Kill switch disengaged. Bot will resume copy-trading on next tick.")


def main():
    parser = argparse.ArgumentParser(description="FOMO Copy-Trading Bot CLI")
    parser.add_argument("--config", "-c", default="config/config.yaml", help="Path to config file")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status
    sub_status = subparsers.add_parser("status", help="Show current bot status and positions")

    # Traders
    sub_traders = subparsers.add_parser("traders", help="View top profitable traders on FOMO leaderboard")
    sub_traders.add_argument("--timeframe", default="7d", choices=["24h", "7d", "30d", "all_time"])
    sub_traders.add_argument("--limit", type=int, default=10)

    # Follow
    sub_follow = subparsers.add_parser("follow", help="Add a trader address to follow")
    sub_follow.add_argument("address", help="Solana address or FOMO handle")

    # Kill
    sub_kill = subparsers.add_parser("kill", help="Engage emergency kill switch")

    # Resume
    sub_resume = subparsers.add_parser("resume", help="Disengage emergency kill switch")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "traders":
        cmd_traders(args)
    elif args.command == "follow":
        cmd_follow(args)
    elif args.command == "kill":
        cmd_kill(args)
    elif args.command == "resume":
        cmd_resume(args)
    else:
        cmd_status(args)


if __name__ == "__main__":
    main()
