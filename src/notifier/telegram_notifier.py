"""
Telegram Alert Dispatcher.
Sends instant notifications for trade entries, multi-level take-profits,
stop-loss exits, and risk circuit breaker activations.
"""
import json
import logging
import urllib.request
import urllib.error
from typing import Optional
from src.config import BotConfig

logger = logging.getLogger("fomo_bot.telegram")


class TelegramNotifier:

    def __init__(self, config: BotConfig):
        self.config = config
        self.enabled = config.telegram_enabled and bool(config.telegram_bot_token and config.telegram_chat_id)
        self.bot_token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id

    def send_message(self, message: str) -> bool:
        """Sends a markdown-formatted message to the operator's Telegram chat."""
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Telegram notification failed to send: %s", e)
            return False

    def notify_entry(self, symbol: str, mint: str, size_usd: float, price_usd: float, trader: str, mode: str):
        if not self.config.notify_on_entry:
            return
        tag = "🟢 [PAPER BUY]" if mode == "paper" else "🚀 [LIVE BUY]"
        text = (
            f"*{tag} Copied FOMO Trader*\n"
            f"• *Token:* `{symbol}`\n"
            f"• *Size:* `${size_usd:,.2f}`\n"
            f"• *Entry Price:* `${price_usd:,.6f}`\n"
            f"• *Trader:* `{trader[:8]}...`\n"
            f"• *Mint:* `{mint[:6]}...{mint[-4:]}`"
        )
        self.send_message(text)

    def notify_exit(self, symbol: str, sell_pct: float, pnl_usd: float, pnl_pct: float, reason: str, mode: str):
        if not self.config.notify_on_exit:
            return
        tag = "🎯 [TAKE PROFIT]" if pnl_usd >= 0 else "🛑 [STOP LOSS]"
        text = (
            f"*{tag} Executed Position Exit*\n"
            f"• *Token:* `{symbol}`\n"
            f"• *Portion Sold:* `{sell_pct:.1f}%`\n"
            f"• *PnL:* `%{pnl_pct:+.2f}%` (`{'+$' if pnl_usd >= 0 else '-$'}{abs(pnl_usd):,.2f}`)\n"
            f"• *Reason:* {reason}\n"
            f"• *Mode:* `{mode.upper()}`"
        )
        self.send_message(text)

    def notify_risk_alert(self, alert_title: str, details: str):
        if not self.config.notify_on_risk_alert:
            return
        text = (
            f"🚨 *RISK CIRCUIT BREAKER TRIGGERED*\n"
            f"• *Event:* *{alert_title}*\n"
            f"• *Details:* {details}\n"
            f"• *Action Taken:* Copy trading paused."
        )
        self.send_message(text)
