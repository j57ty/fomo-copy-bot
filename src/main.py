"""
Main Entrypoint for FOMO Copy-Trading Bot.
Starts the background copy-trading worker and the web health/dashboard service.
"""
import sys
import os
import time
import signal
import threading
import logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import load_config
from src.engine.copy_engine import CopyEngine
from src.web.app import start_web_server

# Setup formatted logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("fomo_bot.main")


def main():
    print("""
    =======================================================
       🚀 FOMO COPY-TRADING BOT (fomo.family)
       Connected to StalkChain MCP (https://data.stalkchain.com/mcp)
       Target Hosting: Render (Web Service / Worker)
    =======================================================
    """)

    config_path = os.getenv("CONFIG_PATH", "config/config.yaml")
    config = load_config(config_path)

    logger.info("Starting bot in [%s] mode...", config.mode.upper())
    logger.info("Followed traders: %s", config.followed_traders)
    logger.info("Max open positions: %d | Trade size: $%s", config.max_open_positions, config.trade_size_usd)
    logger.info("Safety limits: Daily loss limit: $%.2f | Max Drawdown: %.1f%%", config.max_daily_loss_usd, config.max_portfolio_drawdown_pct)

    # Initialize Copy Engine
    engine = CopyEngine(config)
    engine.is_running = True

    # Start Web Dashboard & Render Health Service in background thread
    web_server = start_web_server(copy_engine=engine, host=config.web_host, port=config.web_port)
    server_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    server_thread.start()

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received. Stopping bot gracefully...")
        engine.is_running = False
        web_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Copy-trading execution loop active. Polling every %d seconds...", config.poll_interval_seconds)

    # Main Execution Loop
    tick_count = 0
    try:
        while engine.is_running:
            try:
                engine.tick()
                tick_count += 1
                if tick_count % 12 == 0:  # Log status summary every ~1 minute
                    status = engine.get_status()
                    logger.info(
                        "📊 STATUS: Total: $%.2f | Cash: $%.2f | Open Pos: %d | Realized: %+$%.2f | Unrealized: %+$%.2f | DD: %.1f%%",
                        status.total_portfolio_usd, status.cash_balance_usd, status.open_positions_count,
                        status.realized_pnl_usd, status.unrealized_pnl_usd, status.current_drawdown_pct
                    )
            except Exception as e:
                logger.error("Error during execution tick: %s", e, exc_info=True)

            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        handle_shutdown(None, None)


if __name__ == "__main__":
    main()
