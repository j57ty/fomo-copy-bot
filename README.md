# 🚀 FOMO Copy-Trading Bot

A production-grade, non-custodial crypto copy-trading bot specifically engineered for copying top **FOMO** ([fomo.family](https://fomo.family/)) traders. Designed to run 24/7 as a managed Web Service or Background Worker on **Render**, with on-chain data sourced from the **StalkChain MCP Server** (`https://data.stalkchain.com/mcp`) and DEX order routing via **Jupiter Swap v6** on Solana.

---

## 🏛️ System Architecture

The bot enforces a strict separation of concerns across 5 modular layers:

```
┌────────────────────────────────────────────────────────┐
│                   StalkChain MCP Layer                 │
│  - stalkchain_fomo_leaderboard (24h/7d/30d/all-time)   │
│  - stalkchain_fomo_resolve_trader                      │
│  - stalkchain_fomo_trader_positions / trader_swaps     │
└──────────────────────────┬─────────────────────────────┘
                           │ Stream of Swap Events
                           ▼
┌────────────────────────────────────────────────────────┐
│                   Filter Engine                        │
│  - Chase % Guard (Skip if pumped > max_chase_pct)     │
│  - Liquidity Floor & Market Cap Boundaries             │
│  - First-Buy-Only Filter (Avoid compounding dips)      │
│  - Token Cooldown Timer (Prevent duplicate buys)       │
└──────────────────────────┬─────────────────────────────┘
                           │ Approved Candidate Swaps
                           ▼
┌────────────────────────────────────────────────────────┐
│               Risk Management Circuit Breakers         │
│  - Hard Daily Realized Loss Limit (24h rolling)        │
│  - Peak Portfolio Drawdown Breaker (e.g. 20% limit)    │
│  - Maximum Open Positions Cap                          │
│  - Emergency Kill Switch (File / Web UI / Telegram)    │
└──────────────────────────┬─────────────────────────────┘
                           │ Sized & Validated Orders
                           ▼
┌────────────────────────────────────────────────────────┐
│                   Execution Layer                      │
│  ├─ Paper Trading Mode (Default, Simulated Slippage)   │
│  └─ Solana Live Mode (Dedicated Wallet + Jupiter v6)   │
└──────────────────────────┬─────────────────────────────┘
                           │ Real-time State & Logs
                           ▼
┌────────────────────────────────────────────────────────┐
│               User Controls & Monitoring               │
│  - Web Dashboard UI (Live metrics & trade log)         │
│  - Render Health Check Endpoint (/healthz)             │
│  - Interactive CLI (python -m src.cli status/traders)  │
│  - Telegram Notifier (Entries, Exits, Alerts)          │
└────────────────────────────────────────────────────────┘
```

---

## 🛡️ Critical Wallet Safety & Isolation

> [!CAUTION]
> **NEVER USE YOUR MAIN WALLET OR ANY WALLET HOLDING LONG-TERM ASSETS.**
> Copy-trading involves rapid memecoin interactions. Only use a **new, dedicated trading wallet** holding the minimum amount of capital you are willing to risk.

### Dedicated Solana Wallet Setup Guide

1. **Generate a fresh dedicated keypair**:
   ```bash
   # Option A: Using Solana CLI
   solana-keygen new --outfile ~/dedicated_fomo_bot.json

   # Option B: Using Phantom / Backpack / Solflare
   # Create a brand new wallet address (do not reuse existing accounts).
   # Export its private key (Base58 string).
   ```

2. **Depositing Funds into the Dedicated Wallet**:
   - Send only your designated trading budget (e.g. 0.5 – 2 SOL) to the public address of your new dedicated wallet.
   - Maintain a minimum of **0.05 SOL** at all times to cover Solana transaction fees and rent.

3. **Withdrawing Profits**:
   - Because this bot is completely non-custodial, your funds remain in your Solana keypair on-chain.
   - To withdraw, simply transfer SOL or SPL tokens from your dedicated trading wallet back to your cold storage or personal wallet using Phantom/Backpack or CLI:
     ```bash
     solana transfer <YOUR_MAIN_COLD_WALLET> ALL --keypair ~/dedicated_fomo_bot.json
     ```

4. **Hard Circuit Breakers**:
   - **Daily Loss Limit (`max_daily_loss_usd`)**: If net losses within 24 hours exceed this threshold (e.g. $150), copying halts immediately.
   - **Portfolio Drawdown (`max_portfolio_drawdown_pct`)**: If portfolio drops by >20% from its all-time high, the bot enters lockdown. The bot cannot override this.
   - **Emergency Kill Switch**: Pauses all copying instantly.
     - Web UI: Click **🚨 KILL SWITCH**
     - CLI: `python -m src.cli kill`
     - File: Touch `.killswitch`
     - Telegram: `/kill`

---

## ⚡ Quickstart (Local Paper Trading)

The bot starts in **Paper Trading Mode** by default. No real funds or private keys are required.

### 1. Clone & Setup

```bash
git clone <repo_url>
cd fomo-copy-bot

# Optional: Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Test Suite

```bash
python -m unittest discover -s tests -p "test_*.py"
```

### 3. Check FOMO Leaderboard via CLI

```bash
# View top traders on FOMO (StalkChain 7d leaderboard)
python -m src.cli traders --timeframe 7d --limit 5

# Check current paper portfolio status
python -m src.cli status
```

### 4. Start the Bot Worker & Web Dashboard

```bash
python -m src.main
```
Open your browser to: **`http://localhost:8080`** to inspect the live dashboard, view active positions, and monitor execution decisions.

---

## ⚙️ Configuration Reference (`config/config.yaml`)

```yaml
bot:
  mode: "paper" # 'paper' (default) or 'live'
  name: "FOMO Alpha Copy Bot"
  poll_interval_seconds: 5

stalkchain:
  mcp_url: "https://data.stalkchain.com/mcp"
  leaderboard_timeframe: "7d" # '24h', '7d', '30d', 'all_time'
  auto_sync_top_traders: false # Auto-follow top N traders
  top_traders_count: 3

# Selected traders to follow (Solana addresses or handles)
traders:
  - "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
  - "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH"

trading:
  size_mode: "fixed" # 'fixed' ($50) or 'percent' (5% of portfolio)
  trade_size_usd: 50.0
  max_open_positions: 5
  max_chase_pct: 5.0 # Skip trade if price pumped >5% since trader's fill
  copy_first_buy_only: true # Copy only initial buys (avoids compounding into dumps)
  token_cooldown_seconds: 600 # 10 min cooldown on duplicate token entries
  mirror_sells: false # Independent exits! Do not mirror trader sells

filters:
  min_liquidity_usd: 25000.0 # $25k liquidity floor
  min_market_cap_usd: 50000.0 # $50k mcap floor
  max_market_cap_usd: 25000000.0 # $25M mcap ceiling

exits:
  # Independent Multi-Level Take-Profit Rules
  take_profit_levels:
    - trigger_pct: 100.0 # Sell 50% at +100% (2x)
      sell_pct: 50.0
    - trigger_pct: 300.0 # Sell 25% at +300% (4x)
      sell_pct: 25.0
    - trigger_pct: 500.0 # Sell remaining 100% at +500% (6x)
      sell_pct: 100.0
  stop_loss_pct: -35.0 # Hard stop-loss at -35%

safety:
  max_daily_loss_usd: 150.0 # Circuit breaker for rolling 24h loss
  max_portfolio_drawdown_pct: 20.0 # Circuit breaker for drawdown from peak
  kill_switch: false
```

---

## ☁️ Deploying on Render

The repository includes a ready-to-deploy **`render.yaml`** (Render Blueprint) and a production-grade multi-stage **`docker/Dockerfile`**.

### Method 1: Render Blueprint (Recommended - 1 Click)

1. Push this repository to your GitHub/GitLab account.
2. In the [Render Dashboard](https://dashboard.render.com/), click **New +** -> **Blueprint**.
3. Connect your repository. Render will automatically detect `render.yaml`.
4. Configure your environment variables in the Render settings:
   - `BOT_MODE`: `paper` (or `live` when ready)
   - `CONFIRM_LIVE_TRADING`: `false` (set `true` for live)
   - `SOLANA_PRIVATE_KEY`: Private key of your **dedicated** wallet (Secret)
   - `SOLANA_RPC_URL`: Dedicated RPC (e.g. Helius or QuickNode)
   - `TELEGRAM_BOT_TOKEN`: (Optional) Bot token from @BotFather
   - `TELEGRAM_CHAT_ID`: (Optional) Your Telegram user/channel ID
5. Click **Apply**. Render will build and deploy the container.
6. The service exposes health check `/healthz` automatically for zero-downtime health monitoring.

### Method 2: Render Web Service (Manual)

1. Click **New +** -> **Web Service**.
2. Select **Docker** runtime.
3. Set **Dockerfile Path**: `docker/Dockerfile`.
4. Set **Health Check Path**: `/healthz`.
5. Add the environment variables from `.env.example`.
6. Select the **Starter** ($7/mo) instance type for 24/7 background execution.

---

## 📱 Telegram Alert Integration

To receive instant push notifications whenever the bot copies a trader or triggers a Take-Profit/Stop-Loss:
1. Message `@BotFather` on Telegram and create a new bot to receive your `TELEGRAM_BOT_TOKEN`.
2. Message `@userinfobot` to get your numerical `TELEGRAM_CHAT_ID`.
3. Set both variables in your `.env` or Render environment settings:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   TELEGRAM_CHAT_ID=987654321
   ```
4. Alerts will dispatch automatically for:
   - 🟢 `[PAPER BUY]` / `[LIVE BUY]` entries with size, token, and trader address
   - 🎯 `[TAKE PROFIT]` partial/full sales with realized USD and % gain
   - 🛑 `[STOP LOSS]` exits
   - 🚨 Risk circuit breaker trips & Kill switch engagement

---

## 🔒 Safety Verification Checklist Before Enabling Live Mode

- [ ] Tested in **Paper Trading Mode** for at least 48 hours.
- [ ] Created a **separate, dedicated Solana wallet** (never your personal wallet).
- [ ] Funded only with risk capital you can afford to lose.
- [ ] Confirmed `CONFIRM_LIVE_TRADING=true` is set as an environment variable.
- [ ] Loaded `SOLANA_PRIVATE_KEY` strictly via environment variable (never written in code or git).
- [ ] Verified `max_daily_loss_usd` and `max_portfolio_drawdown_pct` match your risk tolerance.
- [ ] Tested the **🚨 KILL SWITCH** from the web UI to verify instant pause behavior.
