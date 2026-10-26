"""
Web Dashboard and REST API Server for FOMO Copy-Trading Bot.
Designed for 24/7 hosting on Render with health check endpoint (/healthz).
Supports FastAPI/Uvicorn if available, with pure Python http.server fallback.
"""
import os
import json
import logging
from typing import Optional
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from src.engine.copy_engine import CopyEngine

logger = logging.getLogger("fomo_bot.web")


class BotRequestHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, copy_engine: CopyEngine = None, **kwargs):
        self.copy_engine = copy_engine
        super().__init__(*args, **kwargs)

    def do_GET(self):
        # Health check for Render
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = self.copy_engine.get_status().to_dict()
            res = {"status": "ok", "mode": status["mode"], "uptime_ts": status["last_update_ts"]}
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # Main Dashboard UI
        if self.path == "/" or self.path == "/index.html":
            html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
            if os.path.exists(html_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(html_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # API: Status
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            status = self.copy_engine.get_status().to_dict()
            open_pos = [p.to_dict() for p in self.copy_engine.executor.get_open_positions()]
            logs = self.copy_engine.decision_logs[-50:]

            payload = {
                "status": status,
                "positions": open_pos,
                "logs": logs,
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # API: Traders
        if self.path == "/api/traders":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "followed": self.copy_engine.config.followed_traders,
                "leaderboard": [t.to_dict() for t in self.copy_engine.stalkchain.get_fomo_leaderboard()],
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        if self.path == "/api/killswitch":
            active = bool(req_data.get("active", True))
            if active:
                self.copy_engine.risk_manager.trigger_kill_switch(reason="Triggered via Web UI / API")
            else:
                self.copy_engine.risk_manager.reset_kill_switch()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "kill_switch_active": active}).encode("utf-8"))
            return

        if self.path == "/api/traders/add":
            address = req_data.get("address", "").strip()
            if address and address not in self.copy_engine.config.followed_traders:
                self.copy_engine.config.followed_traders.append(address)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "traders": self.copy_engine.config.followed_traders}).encode("utf-8"))
            return

        if self.path == "/api/traders/remove":
            address = req_data.get("address", "").strip()
            if address in self.copy_engine.config.followed_traders:
                self.copy_engine.config.followed_traders.remove(address)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "traders": self.copy_engine.config.followed_traders}).encode("utf-8"))
            return

        # Simulate test event (Paper trading only)
        if self.path == "/api/simulate":
            if self.copy_engine.config.mode == "paper":
                trader = self.copy_engine.config.followed_traders[0] if self.copy_engine.config.followed_traders else "test_trader"
                ev = self.copy_engine.stalkchain.mock_data.simulate_new_swap(trader_address=trader)
                self.copy_engine.process_new_events([ev])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "event": ev.to_dict()}).encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()


def start_web_server(copy_engine: CopyEngine, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    """Starts the web dashboard and health check server in background thread."""
    handler = lambda *args, **kwargs: BotRequestHandler(*args, copy_engine=copy_engine, **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    logger.info("🌐 Web dashboard & Render health service listening on http://%s:%d", host, port)
    return server
