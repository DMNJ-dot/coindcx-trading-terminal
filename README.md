# CoinDCX Institutional Algorithmic Trading Terminal

A production-grade, fully automated quantitative trading terminal for perpetual futures on **COINDCX.COM**, featuring an interactive dashboard, quantitative strategy engine, backtesting engine, independent risk management engine, and live execution.

---

## 1. System Overview & Architecture

The application is structured into five decoupled, production-grade subsystems:

1. **Interactive Trading Dashboard (`frontend/`)**: Modern institutional web terminal built with dark theme typography, TradingView Lightweight Charts (candlestick chart with EMA 9, EMA 21, Session VWAP overlays, and entry/exit markers), control panels, open position monitors, order management, filterable trade history with CSV export, real-time logs, and embedded backtest reporting.
2. **Quantitative Strategy Engine (`backend/strategies/`)**: Pure causal calculations of Session VWAP (anchored to 00:00 UTC day), EMA 9, EMA 21, Wilder's ATR(14), and 20-bar volume moving average. Strictly evaluates closed 5-minute candles without lookahead or repainting.
3. **Automated Order Execution Engine (`backend/execution/` & `backend/exchange/`)**: Direct integration with CoinDCX perpetual futures API (`https://api.coindcx.com` and `wss://stream.coindcx.com`) utilizing HMAC-SHA256 request signing, client order ID idempotency, bracket protective orders, slippage modeling, and automatic position reconciliation.
4. **Independent Risk Management Engine (`backend/risk/`)**: Autonomous risk manager with absolute authority to veto entries based on 0.5% capital risk sizing, maximum 10x leverage, -2.0% daily loss halt (IST day), 15-minute post-trade cooldown, maximum 1 open position, and circuit breakers.
5. **Backtesting & Analytics Engine (`backend/backtest/`)**: High-performance historical simulation engine with same-bar ambiguity resolution (pessimistic headline vs. optimistic upper bound), chronological splits (60% Train, 20% Validation, 20% Out-of-Sample), walk-forward windows, sensitivity audits, and pre-registered PASS/FAIL verification.

```
coindcx-trading-terminal/
├── backend/
│   ├── api/                 # FastAPI REST routes and WebSocket streaming
│   ├── backtest/            # Indicators, signals, backtest engine, metrics
│   ├── config/              # Pydantic Settings & environment config
│   ├── database/            # SQLite thread-safe persistence layer
│   ├── exchange/            # CoinDCX REST & WebSocket integration client
│   ├── execution/           # Bracket order manager & reconciliation
│   ├── market_data/         # Live candle aggregator & multi-coin stream
│   ├── monitoring/          # Watchdog service, connection & data health
│   ├── notifications/       # Telegram bot & terminal event notifications
│   ├── portfolio/           # Equity accounting, exposure & statistics
│   ├── risk/                # Autonomous risk controller & circuit breaker
│   ├── strategies/          # Live strategy runner
│   └── tests/               # Pytest automated test suite (19 passed)
├── frontend/
│   ├── index.html           # Institutional trading dashboard interface
│   ├── style.css            # Dark theme styles & grid layout
│   ├── app.js               # WebSocket client & chart bindings
│   └── lightweight-charts.standalone.production.js
├── data/
│   ├── BTCUSDT_5m_3y.csv    # 3-year historical 5m candle dataset
│   └── clean_5m.parquet     # Verified clean dataset (315,648 bars)
├── results/
│   ├── REPORT.md            # Comprehensive quantitative evaluation report
│   ├── trades_primary.csv   # Primary scenario trade lifecycle logs
│   ├── trades_scalper.csv   # Scalper tier comparison trade logs
│   ├── trades_maker.csv     # Maker entry comparison trade logs
│   ├── skipped_signals.csv  # Filter rejection records & audit
│   ├── equity_curve.png     # Full 3-year equity & drawdown chart
│   └── monthly_pnl.png      # Out-of-sample monthly returns chart
├── run.py                   # One-click startup script (auto-opens browser)
├── start.bat                # Windows double-click launcher
├── requirements.txt         # Pinned production dependencies
├── .env.example             # Configuration template
└── README.md
```

---

## 2. Quickstart & Installation

No Docker is required. The application runs locally via Python 3.12.

### Step 1: Clone or Navigate to the Workspace
```powershell
cd C:\Users\dpsla\.gemini\antigravity\scratch\coindcx-trading-terminal
```

### Step 2: Activate the Virtual Environment
A dedicated `.venv` has been pre-configured with all pinned packages:
```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 3: Launch the Application
Run the startup script:
```powershell
python run.py
```
Or simply double-click `start.bat`.

The backend server will start on `http://127.0.0.1:8000` and automatically open your default browser to the interactive dashboard.

---

## 3. Four Operating Modes

| Mode | Real Money? | Execution Target | Protection & Reconciliation |
| :--- | :--- | :--- | :--- |
| **1. Backtesting** | No | Historical 3-Year Parquet | Mathematical simulation across 315,648 bars |
| **2. Paper Trading (Default)** | No | Simulated at Live Prices | Full trade lifecycle, simulated fees & slippage |
| **3. Testnet / Sandbox** | No | Exchange Testnet | Supported sandbox contract endpoints |
| **4. Live Trading** | **YES** | CoinDCX Live Futures API | Real orders, strict 2-step confirmation required |

### Safety Lock for Live Trading:
Live trading is **disabled by default**. Switching to Live Trading requires:
1. Entering authenticated CoinDCX API credentials with IP binding.
2. Clicking **Switch Trading Mode** in the dashboard.
3. Selecting **LIVE TRADING** and explicitly checking the confirmation box.
4. When Live mode is active, the terminal displays a pulsing crimson **LIVE TRADING** alert badge.

---

## 4. Quantitative Strategy Engine: VWAP + EMA Trend Pullback

- **Timeframe**: 5-minute candles (`5m`).
- **Session Window**: 13:00 to 22:00 IST (07:30 to 16:30 UTC), Monday through Friday only. No weekend trading.
- **Indicators**:
  - **Session VWAP**: Anchored to 00:00 UTC day reset: $VWAP = \frac{\sum (TP \times Volume)}{\sum Volume}$ where $TP = \frac{High + Low + Close}{3}$.
  - **EMA 9 & EMA 21**: Exponential moving averages computed on closed bar closes.
  - **ATR(14)**: Wilder's Average True Range over 14 bars.
  - **20-Bar Volume MA**: Moving average of bar volume.
- **Long Entry Rules** (all must be satisfied on closed bars):
  1. Bar inside trading window.
  2. Trend for last 3 closed bars: $Close > VWAP$ and $EMA_9 > EMA_{21}$.
  3. Pullback bar: Low touches within 0.05% of $EMA_{21}$ or $VWAP$ without closing below $VWAP$.
  4. Trigger bar: Closes back above $EMA_9$ and volume $\ge 0.8 \times \text{Volume MA}_{20}$.
  5. Execution: Enter at **NEXT bar's OPEN**.
- **Short Entry Rules**: Exact mirror image.
- **Exit Rules**:
  - **Stop-Loss**: Set at entry beyond pullback swing low (long) / swing high (short) by $0.25 \times ATR(14)$. Floor of 0.20%, cap of 0.35% of entry price. If required stop exceeds 0.35%, skip trade.
  - **Take-Profit**: Exactly $3 \times$ stop distance (planned 1:3 reward-to-risk).
  - **Time-Stop**: Exit at market after 30 minutes (6 closed bars) if neither stop nor target has triggered.

---

## 5. Quantitative Backtesting Results Summary

Evaluated on 315,648 clean 5m candles (`2023-07-01` to `2026-06-30`) under full CoinDCX transaction costs (taker entry 0.059% + taker exit 0.059% + round-trip slippage 0.03% = 0.148% round trip):

- **Data Audit**: 0 gaps, 0 corrupted bars, 0 duplicate timestamps.
- **Total Trades**: 436 trades executed.
- **Out-of-Sample Results (Pessimistic Headline)**:
  - Total OOS Trades: 91 trades.
  - Win Rate: **28.57%**.
  - Net P&L: **-$870.34 (-8.70%)**.
  - Profit Factor: **0.44**.
  - Expectancy: **-$9.56 per trade (-0.360R)**.
  - Max Drawdown: 10.07%.
  - Ambiguity Rate: **0.00%** (Well within the <= 15% pre-registered threshold).
- **Baselines Comparison**:
  - Buy & Hold BTCUSDT: -32.75% (-$3,275.43).
  - Random Entries (20 seeds avg): -$26.97 per trade (-$2,365.06).
  - VWAP+EMA Strategy: -$9.56 per trade (substantially outperforms random entry baseline).
- **Pre-Registered Pass Bars**: 2 Passed, 4 Failed.
- **Verdict**: The strategy loses money after full taker costs and slippage because the 0.148% cost is over half of the 0.20% stop distance, and 65.9% of trades exit at the 30-minute time-stop without reaching target. Live capital should only be deployed if trading on the 0% exit fee Scalper tier or utilizing maker entries.

---

## 6. Automated Test Suite

Run the full pytest suite with 19 passing integration and unit tests:
```powershell
& ".\.venv\Scripts\pytest.exe" backend\tests -v
```

Tests cover:
- Truncation / No-lookahead causal verification.
- Hand-crafted synthetic fixtures with known trades and same-bar ambiguity resolution.
- Same-bar entry/exit protection.
- Stop floor (0.20%) and stop cap (0.35%) boundaries.
- Order execution in Paper and Live safety modes.
- Network timeouts and exchange error resilience.
- Time-stop triggers and position monitoring.
- All REST API endpoints and dashboard control actions.
- Web authentication protection and cloud healthcheck endpoints.

---

## 7. Web Hosting & Cloud Deployment (Free Tiers)

The project includes OS-independent relative paths (`pathlib.Path`), `0.0.0.0:$PORT` server binding, a `/health` probe, optional HTTP Basic Auth protection (`DASHBOARD_PASSWORD`), and deployment manifests (`Procfile`, `runtime.txt`, `render.yaml`, `railway.toml`) without requiring Docker.

### Security for Public Web Links
Set `DASHBOARD_PASSWORD` (and optionally `DASHBOARD_USERNAME`, default `admin`) in your host's environment variables before exposing the dashboard publicly so unauthorized visitors cannot access controls or settings.

### Option A: Render Free Web Service ($0/month, no credit card)
1. Push this folder to a GitHub repository (`.gitignore` excludes `.venv/` and local `.db` files; `data/clean_5m.parquet` is 12.6 MB).
2. In Render, choose **New + → Blueprint** (uses `render.yaml`) or **Web Service**:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/health`
3. *Free-tier caveat*: Render free instances spin down after 15 minutes of inactivity (disconnecting idle WebSockets until the next visit wakes the service) and use an ephemeral filesystem.

### Option B: Railway (Persistent WebSockets & Background Loops)
Use `railway.toml` / `Procfile` to deploy directly on Railway (note: Railway offers free trial credits before usage-based billing).

### Important Note on CoinDCX Live Trading & IP Binding
CoinDCX API keys strictly enforce **IP Binding**. Free cloud tiers use dynamic/shared outbound IP addresses. Use cloud-hosted free tiers for **Paper Trading, Market Monitoring, Backtesting, and Analytics**, or upgrade to a static outbound IP host before enabling Live Trading.

