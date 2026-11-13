/**
 * CoinDCX Algorithmic Trading Terminal Frontend Controller.
 * Fully interactive with live TradingView Lightweight Charts, WebSockets,
 * REST API control bindings, real-time metrics, and backtest reporting.
 */

// Global State
let chart = null;
let candleSeries = null;
let ema9Series = null;
let ema21Series = null;
let vwapSeries = null;
let currentMode = "PAPER";
let socket = null;

function init() {
  try { initNavigation(); } catch (e) { console.error("Navigation init error:", e); }
  try { initChart(); } catch (e) { console.error("Chart init error:", e); }
  try { initControls(); } catch (e) { console.error("Controls init error:", e); }
  try { initForms(); } catch (e) { console.error("Forms init error:", e); }
  try { initWebSocket(); } catch (e) { console.error("WebSocket init error:", e); }
  try { fetchInitialData(); } catch (e) { console.error("Initial data error:", e); }

  // Periodic polling every 3 seconds for continuous updates
  setInterval(refreshDashboardData, 3000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

// 1. Navigation Switching
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  const pages = document.querySelectorAll(".page-view");

  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      navItems.forEach((n) => n.classList.remove("active"));
      pages.forEach((p) => p.classList.remove("active"));

      item.classList.add("active");
      const targetPageId = item.getAttribute("data-page");
      const targetPage = document.getElementById(targetPageId);
      if (targetPage) {
        targetPage.classList.add("active");
      }

      if (targetPageId === "page-live" && chart) {
        setTimeout(() => {
          resizeChart();
        }, 100);
      } else if (targetPageId === "page-backtest") {
        loadBacktestReport();
      }
    });
  });
}

// 2. Interactive Candlestick Chart (Lightweight Charts)
function initChart() {
  const container = document.getElementById("chart-container");
  if (!container || !window.LightweightCharts) return;

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 800,
    height: 520,
    layout: {
      background: { color: "#121824" },
      textColor: "#9ca3af",
    },
    grid: {
      vertLines: { color: "#1f293d" },
      horzLines: { color: "#1f293d" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "#26354d",
    },
    timeScale: {
      borderColor: "#26354d",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#10b981",
    downColor: "#ef4444",
    borderDownColor: "#ef4444",
    borderUpColor: "#10b981",
    wickDownColor: "#ef4444",
    wickUpColor: "#10b981",
  });

  ema9Series = chart.addLineSeries({
    color: "#3b82f6",
    lineWidth: 1.5,
    title: "EMA 9",
  });

  ema21Series = chart.addLineSeries({
    color: "#f59e0b",
    lineWidth: 1.5,
    title: "EMA 21",
  });

  vwapSeries = chart.addLineSeries({
    color: "#ec4899",
    lineWidth: 1.8,
    title: "Session VWAP",
  });

  window.addEventListener("resize", resizeChart);
}

function resizeChart() {
  const container = document.getElementById("chart-container");
  if (chart && container) {
    chart.applyOptions({
      width: container.clientWidth,
      height: 520,
    });
  }
}

// 3. Trading Controls & Modal
function initControls() {
  const btnStart = document.getElementById("btn-start-bot");
  const btnStop = document.getElementById("btn-stop-bot");
  const btnEnableAuto = document.getElementById("btn-enable-auto");
  const btnDisableAuto = document.getElementById("btn-disable-auto");
  const btnSwitchMode = document.getElementById("btn-switch-mode");
  const btnClosePos = document.getElementById("btn-close-pos");
  const btnEmergency = document.getElementById("btn-emergency");
  const btnTopEmergency = document.getElementById("btn-top-emergency");

  btnStart?.addEventListener("click", () => postControl("/api/control/start"));
  btnStop?.addEventListener("click", () => postControl("/api/control/stop"));
  btnEnableAuto?.addEventListener("click", () => postControl("/api/control/auto_trading?enabled=true"));
  btnDisableAuto?.addEventListener("click", () => postControl("/api/control/pause"));
  btnEmergency?.addEventListener("click", confirmEmergencyStop);
  btnTopEmergency?.addEventListener("click", confirmEmergencyStop);

  btnClosePos?.addEventListener("click", () => {
    fetch("/api/positions")
      .then((r) => r.json())
      .then((data) => {
        if (data.open_positions && data.open_positions.length > 0) {
          const posId = data.open_positions[0].position_id;
          if (confirm(`Confirm closing position ${posId}?`)) {
            postControl(`/api/control/close_position?position_id=${posId}`);
          }
        } else {
          alert("No open positions to close.");
        }
      });
  });

  // Modal logic for mode switching
  const modal = document.getElementById("modal-mode");
  const btnCancel = document.getElementById("btn-modal-cancel");
  const btnConfirm = document.getElementById("btn-modal-confirm");
  const liveBox = document.getElementById("live-confirm-box");
  const radioLive = document.querySelector('input[name="opt-mode"][value="live"]');
  const radioAll = document.querySelectorAll('input[name="opt-mode"]');

  btnSwitchMode?.addEventListener("click", () => {
    modal.classList.add("active");
  });

  btnCancel?.addEventListener("click", () => {
    modal.classList.remove("active");
  });

  radioAll.forEach((r) => {
    r.addEventListener("change", (e) => {
      if (e.target.value === "live") {
        liveBox.style.display = "block";
      } else {
        liveBox.style.display = "none";
      }
    });
  });

  btnConfirm?.addEventListener("click", () => {
    const selected = document.querySelector('input[name="opt-mode"]:checked')?.value;
    const confirmLive = document.getElementById("chk-live-confirm")?.checked || false;

    if (selected === "live" && !confirmLive) {
      alert("You must check the confirmation checkbox before enabling LIVE TRADING!");
      return;
    }

    fetch("/api/control/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: selected, confirm_live: confirmLive }),
    })
      .then((r) => r.json())
      .then((res) => {
        modal.classList.remove("active");
        if (res.success) {
          alert(`Switched operating mode to ${res.trading_mode}`);
          refreshDashboardData();
        } else {
          alert(`Mode switch failed: ${res.detail || res.error}`);
        }
      });
  });

  // Export CSV button
  document.getElementById("btn-export-csv")?.addEventListener("click", () => {
    window.location.href = "/api/trades/export_csv";
  });

  // Refresh logs button
  document.getElementById("btn-refresh-logs")?.addEventListener("click", loadLogs);

  // Run backtest button
  document.getElementById("btn-run-backtest")?.addEventListener("click", runBacktest);
}

function confirmEmergencyStop() {
  if (confirm("EMERGENCY STOP WARNING:\nThis will halt all new entries and close all open positions immediately. Proceed?")) {
    postControl("/api/control/emergency_stop");
  }
}

function postControl(endpoint) {
  fetch(endpoint, { method: "POST" })
    .then((r) => r.json())
    .then((res) => {
      refreshDashboardData();
    })
    .catch((err) => console.error("Control error:", err));
}

// 4. Forms
function initForms() {
  // Strategy Config
  const formCfg = document.getElementById("form-strategy-config");
  formCfg?.addEventListener("submit", (e) => {
    e.preventDefault();
    const payload = {
      default_symbol: document.getElementById("cfg-symbol").value,
      ema_fast_period: parseInt(document.getElementById("cfg-ema-fast").value),
      ema_slow_period: parseInt(document.getElementById("cfg-ema-slow").value),
      atr_period: parseInt(document.getElementById("cfg-atr-period").value),
      vol_ma_period: parseInt(document.getElementById("cfg-vol-ma-period").value),
      vol_trigger_multiplier: parseFloat(document.getElementById("cfg-vol-mult").value),
      stop_atr_multiplier: parseFloat(document.getElementById("cfg-stop-atr").value),
      take_profit_rr: parseFloat(document.getElementById("cfg-tp-rr").value),
      risk_pct_per_trade: parseFloat(document.getElementById("cfg-risk-pct").value) / 100.0,
      max_leverage: parseFloat(document.getElementById("cfg-leverage").value),
      daily_loss_limit_pct: parseFloat(document.getElementById("cfg-daily-loss").value) / 100.0,
      cooldown_bars: parseInt(document.getElementById("cfg-cooldown").value),
      max_hold_bars: parseInt(document.getElementById("cfg-max-hold").value),
      slippage_rate: parseFloat(document.getElementById("cfg-slippage").value) / 100.0,
    };

    fetch("/api/strategy/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((res) => {
        alert("Strategy configuration saved successfully.");
      });
  });

  // Credentials
  const formCreds = document.getElementById("form-credentials");
  formCreds?.addEventListener("submit", (e) => {
    e.preventDefault();
    const payload = {
      api_key: document.getElementById("set-api-key").value,
      api_secret: document.getElementById("set-api-secret").value,
      telegram_bot_token: document.getElementById("set-telegram-token").value,
      telegram_chat_id: document.getElementById("set-telegram-chat").value,
    };

    fetch("/api/settings/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((res) => {
        alert(res.message || "Credentials updated.");
      });
  });
}

// 5. WebSocket Integration
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  socket = new WebSocket(wsUrl);

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "TELEMETRY_UPDATE") {
        updateTickerUI(data.ticker);
        updateBotUI(data.bot_status);
      }
    } catch (e) {}
  };

  socket.onclose = () => {
    setTimeout(initWebSocket, 2000);
  };
}

// 6. Data Refreshing Functions
function fetchInitialData() {
  refreshDashboardData();
  loadCandles();
  loadPositions();
  loadOrders();
  loadTradeHistory();
  loadLogs();
  loadStrategyConfig();
}

function refreshDashboardData() {
  fetch("/api/dashboard/overview")
    .then((r) => r.json())
    .then((data) => {
      // Account
      const acc = data.account;
      setText("card-equity", `$${acc.current_equity.toFixed(2)}`);
      setText("card-today-pnl", `$${acc.today_pnl.toFixed(2)}`);
      setText("card-realised-pnl", `$${acc.realised_pnl.toFixed(2)}`);
      setText("card-unrealised-pnl", `$${acc.unrealised_pnl.toFixed(2)}`);
      setText("card-used-margin", `$${acc.used_margin.toFixed(2)}`);
      setText("card-leverage", `${acc.current_leverage.toFixed(2)}x`);
      setText("card-exposure", `$${acc.current_account_exposure.toFixed(2)}`);
      setText("an-dd-usd", `$${acc.maximum_drawdown_usd.toFixed(2)}`);
      setText("an-dd-pct", `${acc.maximum_drawdown_pct.toFixed(2)}%`);

      // Trading Mode Badge
      const modeBadge = document.getElementById("badge-trading-mode");
      if (modeBadge) {
        modeBadge.innerText = `${acc.trading_mode} TRADING`;
        if (acc.trading_mode === "LIVE") {
          modeBadge.className = "badge-mode badge-live";
        } else {
          modeBadge.className = "badge-mode badge-paper";
        }
      }

      // Stats
      const stat = data.statistics;
      setText("stat-total-trades", stat.total_trades);
      setText("stat-win-rate", `${stat.win_rate.toFixed(1)}%`);
      setText("stat-profit-factor", stat.profit_factor.toFixed(2));
      setText("stat-expectancy", `$${stat.expectancy.toFixed(2)}`);
      setText("stat-avg-win-loss", `$${stat.avg_win.toFixed(2)} / $${stat.avg_loss.toFixed(2)}`);
      setText("stat-max-streak", stat.max_consecutive_losses);
      setText("an-pf", stat.profit_factor.toFixed(2));

      // Market Ticker
      updateTickerUI(data.market);

      // Bot Status
      updateBotUI(data.bot_status);

      // Health
      const health = data.health;
      const dotEx = document.getElementById("dot-exchange");
      const dotData = document.getElementById("dot-data");
      if (dotEx) dotEx.className = health.exchange_status === "ONLINE" ? "status-dot" : "status-dot red";
      if (dotData) dotData.className = health.market_data_status === "STREAMING" ? "status-dot" : "status-dot red";
    });

  loadPositions();
}

function updateTickerUI(ticker) {
  if (!ticker) return;
  setText("top-symbol", ticker.symbol);
  setText("top-price", `$${ticker.price.toFixed(2)}`);
  setText("top-trend", ticker.trend);
  setText("top-vwap", `$${ticker.vwap.toFixed(2)}`);
  setText("top-ema9", `$${ticker.ema9.toFixed(2)}`);
  setText("top-ema21", `$${ticker.ema21.toFixed(2)}`);

  const changeEl = document.getElementById("top-change");
  if (changeEl) {
    const chg = ticker.change_24h_pct;
    changeEl.innerText = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;
    changeEl.className = chg >= 0 ? "ticker-change pos" : "ticker-change neg";
  }
}

function updateBotUI(status) {
  if (!status) return;
  setText("bot-state-text", status.bot_running ? "RUNNING" : "STOPPED");
  setText("bot-autotrade-text", status.auto_trading_enabled ? "ENABLED" : "DISABLED");
  setText("bot-last-signal", status.last_signal_time || "None");
  setText("bot-last-exec", status.last_executed_trade || "None");

  const haltEl = document.getElementById("risk-halt-status");
  if (haltEl) {
    if (status.emergency_halt) {
      haltEl.innerText = "HALTED / EMERGENCY STOP";
      haltEl.style.color = "var(--accent-red)";
    } else {
      haltEl.innerText = "NORMAL / ACTIVE";
      haltEl.style.color = "var(--accent-green)";
    }
  }
}

function loadCandles() {
  fetch("/api/market/candles?count=200")
    .then((r) => r.json())
    .then((data) => {
      if (!data.candles || !candleSeries) return;

      const candles = data.candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
      candleSeries.setData(candles);

      const ema9 = data.candles.filter((c) => c.ema9 !== null).map((c) => ({ time: c.time, value: c.ema9 }));
      const ema21 = data.candles.filter((c) => c.ema21 !== null).map((c) => ({ time: c.time, value: c.ema21 }));
      const vwap = data.candles.filter((c) => c.vwap !== null).map((c) => ({ time: c.time, value: c.vwap }));

      if (ema9Series) ema9Series.setData(ema9);
      if (ema21Series) ema21Series.setData(ema21);
      if (vwapSeries) vwapSeries.setData(vwap);
    });
}

function loadPositions() {
  fetch("/api/positions")
    .then((r) => r.json())
    .then((data) => {
      renderPositionsTable("table-live-positions", data.open_positions);
      renderPositionsTable("table-positions-full", data.open_positions);
    });
}

function renderPositionsTable(tableId, positions) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="12" style="text-align: center; color: var(--text-muted);">No open positions.</td></tr>`;
    return;
  }

  tbody.innerHTML = positions
    .map(
      (p) => `
    <tr>
      <td>${p.position_id}</td>
      <td><strong>${p.symbol}</strong></td>
      <td style="color: ${p.side === "LONG" ? "var(--accent-green)" : "var(--accent-red)"}; font-weight: bold;">${p.side}</td>
      <td>${p.quantity.toFixed(4)}</td>
      <td>$${p.entry_price.toFixed(2)}</td>
      <td>$${p.current_price.toFixed(2)}</td>
      <td style="color: var(--accent-red);">$${p.stop_loss ? p.stop_loss.toFixed(2) : "N/A"}</td>
      <td style="color: var(--accent-green);">$${p.take_profit ? p.take_profit.toFixed(2) : "N/A"}</td>
      <td style="color: ${p.unrealised_pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)"}; font-weight: bold;">
        ${p.unrealised_pnl >= 0 ? "+" : ""}$${p.unrealised_pnl.toFixed(2)}
      </td>
      <td>${p.bars_held || 0}</td>
      <td>
        <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="closeSpecificPosition('${p.position_id}')">Close</button>
      </td>
    </tr>
  `
    )
    .join("");
}

window.closeSpecificPosition = function (posId) {
  if (confirm(`Confirm closing position ${posId}?`)) {
    postControl(`/api/control/close_position?position_id=${posId}`);
  }
};

function loadOrders() {
  fetch("/api/orders?limit=50")
    .then((r) => r.json())
    .then((data) => {
      const tbody = document.querySelector("#table-orders tbody");
      if (!tbody) return;

      if (!data.orders || data.orders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="12" style="text-align: center; color: var(--text-muted);">No orders recorded.</td></tr>`;
        return;
      }

      tbody.innerHTML = data.orders
        .map(
          (o) => `
        <tr>
          <td>${o.order_id}</td>
          <td>${o.client_order_id || "-"}</td>
          <td>${o.symbol}</td>
          <td style="color: ${o.side.toUpperCase() === "BUY" ? "var(--accent-green)" : "var(--accent-red)"}; font-weight: bold;">${o.side.toUpperCase()}</td>
          <td>${o.order_type}</td>
          <td>$${o.price ? o.price.toFixed(2) : "MKT"}</td>
          <td>${o.quantity.toFixed(4)}</td>
          <td>${o.filled_quantity ? o.filled_quantity.toFixed(4) : "0"}</td>
          <td>$${o.average_fill_price ? o.average_fill_price.toFixed(2) : "0.00"}</td>
          <td><span style="font-weight: bold; color: ${o.status === "FILLED" ? "var(--accent-green)" : "var(--text-secondary)"};">${o.status}</span></td>
          <td>$${o.fees ? o.fees.toFixed(2) : "0.00"}</td>
          <td>${o.created_at}</td>
        </tr>
      `
        )
        .join("");
    });
}

function loadTradeHistory() {
  fetch("/api/trades?limit=100")
    .then((r) => r.json())
    .then((data) => {
      const tbody = document.querySelector("#table-history tbody");
      if (!tbody) return;

      if (!data.trades || data.trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="13" style="text-align: center; color: var(--text-muted);">No completed trades.</td></tr>`;
        return;
      }

      tbody.innerHTML = data.trades
        .map(
          (t) => `
        <tr>
          <td>${t.trade_id}</td>
          <td>${t.symbol}</td>
          <td style="color: ${t.side === "LONG" ? "var(--accent-green)" : "var(--accent-red)"}; font-weight: bold;">${t.side}</td>
          <td>${t.entry_time.replace("T", " ").replace("Z", "")}</td>
          <td>${t.exit_time.replace("T", " ").replace("Z", "")}</td>
          <td>$${t.entry_price.toFixed(2)}</td>
          <td>$${t.exit_price.toFixed(2)}</td>
          <td>$${t.stop_price.toFixed(2)}</td>
          <td>$${t.target_price.toFixed(2)}</td>
          <td><span style="font-size: 11px; padding: 2px 6px; border-radius: 4px; background: var(--bg-card);">${t.exit_reason}</span></td>
          <td>${t.bars_held}</td>
          <td style="color: ${t.net_pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)"}; font-weight: bold;">
            ${t.net_pnl >= 0 ? "+" : ""}$${t.net_pnl.toFixed(2)}
          </td>
          <td style="color: ${t.realised_r >= 0 ? "var(--accent-green)" : "var(--accent-red)"};">${t.realised_r.toFixed(2)}R</td>
        </tr>
      `
        )
        .join("");
    });
}

function loadLogs() {
  fetch("/api/logs?limit=80")
    .then((r) => r.json())
    .then((data) => {
      const container = document.getElementById("log-feed");
      if (!container) return;

      container.innerHTML = data.logs
        .map(
          (l) => `
        <div class="log-entry">
          <span class="log-ts">[${l.timestamp.replace("T", " ").replace("Z", "")}]</span>
          <span class="log-lvl-${l.level}">[${l.level}]</span>
          <span style="color: var(--accent-purple);">[${l.category}]</span>
          <span>${l.message}</span>
        </div>
      `
        )
        .join("");
    });
}

function loadStrategyConfig() {
  fetch("/api/strategy/config")
    .then((r) => r.json())
    .then((cfg) => {
      setValue("cfg-symbol", cfg.default_symbol);
      setValue("cfg-ema-fast", cfg.ema_fast_period);
      setValue("cfg-ema-slow", cfg.ema_slow_period);
      setValue("cfg-atr-period", cfg.atr_period);
      setValue("cfg-vol-ma-period", cfg.vol_ma_period);
      setValue("cfg-vol-mult", cfg.vol_trigger_multiplier);
      setValue("cfg-stop-atr", cfg.stop_atr_multiplier);
      setValue("cfg-tp-rr", cfg.take_profit_rr);
      setValue("cfg-risk-pct", cfg.risk_pct_per_trade * 100);
      setValue("cfg-leverage", cfg.max_leverage);
      setValue("cfg-daily-loss", cfg.daily_loss_limit_pct * 100);
      setValue("cfg-cooldown", cfg.cooldown_bars);
      setValue("cfg-max-hold", cfg.max_hold_bars);
      setValue("cfg-slippage", cfg.slippage_rate * 100);
    });
}

function loadBacktestReport() {
  fetch("/api/backtest/report")
    .then((r) => r.json())
    .then((data) => {
      const reportBox = document.getElementById("report-content");
      if (reportBox) {
        reportBox.innerText = data.report_markdown;
      }
    });
}

function runBacktest() {
  const btn = document.getElementById("btn-run-backtest");
  if (btn) btn.innerText = "⏳ Running Backtest...";

  fetch("/api/backtest/run", { method: "POST" })
    .then((r) => r.json())
    .then((res) => {
      if (btn) btn.innerText = "▶ Run Backtest Simulation";
      alert("Historical backtest complete!");
      loadBacktestReport();
      // Reload charts images with cache buster
      const img1 = document.getElementById("img-equity-curve");
      const img2 = document.getElementById("img-monthly-pnl");
      if (img1) img1.src = `/results/equity_curve.png?v=${Date.now()}`;
      if (img2) img2.src = `/results/monthly_pnl.png?v=${Date.now()}`;
    })
    .catch((err) => {
      if (btn) btn.innerText = "▶ Run Backtest Simulation";
      alert("Backtest failed: " + err);
    });
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.innerText = text;
}

function setValue(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}
