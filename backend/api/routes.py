"""
FastAPI REST Routes for Trading Terminal Dashboard & API Controls.
Every button, setting, chart, position, order, and backtest action is wired here.
"""
import os
import io
import csv
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from backend.config.settings import settings, RESULTS_DIR
from backend.database.db import db
from backend.market_data.stream_manager import market_data_manager
from backend.strategies.strategy_engine import strategy_engine
from backend.execution.executor import executor
from backend.risk.risk_manager import risk_manager
from backend.portfolio.portfolio_tracker import portfolio_tracker
from backend.monitoring.health_monitor import health_monitor
from backend.exchange.coindcx_client import exchange_client
from backend.backtest.run_backtest import run_full_evaluation


api_router = APIRouter(prefix="/api")


# Request Models
class StrategyConfigModel(BaseModel):
    default_symbol: Optional[str] = None
    timeframe: Optional[str] = None
    ema_fast_period: Optional[int] = None
    ema_slow_period: Optional[int] = None
    atr_period: Optional[int] = None
    vol_ma_period: Optional[int] = None
    vol_trigger_multiplier: Optional[float] = None
    pullback_tolerance: Optional[float] = None
    stop_atr_multiplier: Optional[float] = None
    min_stop_pct: Optional[float] = None
    max_stop_pct: Optional[float] = None
    take_profit_rr: Optional[float] = None
    max_hold_bars: Optional[int] = None
    session_start_hour: Optional[float] = None
    session_end_hour: Optional[float] = None
    risk_pct_per_trade: Optional[float] = None
    max_leverage: Optional[float] = None
    daily_loss_limit_pct: Optional[float] = None
    cooldown_bars: Optional[int] = None
    max_open_positions: Optional[int] = None
    slippage_rate: Optional[float] = None


class ModeSwitchModel(BaseModel):
    mode: str  # 'paper', 'testnet', 'live', 'backtest'
    confirm_live: bool = False


class CredentialsModel(BaseModel):
    api_key: str
    api_secret: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


# 1. Main Dashboard Overview
@api_router.get("/dashboard/overview")
def get_dashboard_overview():
    return {
        "account": portfolio_tracker.get_account_overview(),
        "market": market_data_manager.get_latest_ticker(),
        "statistics": portfolio_tracker.get_trading_statistics(),
        "bot_status": strategy_engine.get_status(),
        "health": health_monitor.get_health_summary(),
    }


# 2. Interactive Candlestick Chart Data
@api_router.get("/market/candles")
def get_market_candles(count: int = Query(200, ge=10, le=500)):
    candles = market_data_manager.get_latest_candles(count=count)
    return {
        "symbol": market_data_manager.symbol,
        "timeframe": market_data_manager.timeframe,
        "candles": candles,
    }


# 3. Trading Controls
@api_router.post("/control/start")
def start_bot():
    market_data_manager.start()
    strategy_engine.start()
    return {"success": True, "message": "Bot and strategy engine started."}


@api_router.post("/control/stop")
def stop_bot():
    strategy_engine.stop()
    return {"success": True, "message": "Strategy engine stopped."}


@api_router.post("/control/pause")
def pause_entries():
    strategy_engine.set_auto_trading(False)
    return {"success": True, "message": "New entries paused."}


@api_router.post("/control/resume")
def resume_trading():
    risk_manager.resume_trading()
    strategy_engine.set_auto_trading(True)
    return {"success": True, "message": "Trading resumed."}


@api_router.post("/control/emergency_stop")
def emergency_stop():
    res = executor.emergency_stop_all()
    strategy_engine.set_auto_trading(False)
    return res


@api_router.post("/control/auto_trading")
def toggle_auto_trading(enabled: bool):
    strategy_engine.set_auto_trading(enabled)
    return {"success": True, "auto_trading_enabled": enabled}


@api_router.post("/control/mode")
def switch_trading_mode(payload: ModeSwitchModel):
    mode = payload.mode.lower()
    if mode not in ["paper", "testnet", "live", "backtest"]:
        raise HTTPException(status_code=400, detail="Invalid trading mode.")

    if mode == "live":
        if not payload.confirm_live:
            raise HTTPException(status_code=400, detail="Live trading requires explicit confirmation!")
        settings.trading_mode = "live"
        settings.live_trading_confirmed = True
        db.log_event("WARNING", "MODE_SWITCH", "LIVE TRADING ACTIVATED WITH REAL CAPITAL!")
    else:
        settings.trading_mode = mode
        settings.live_trading_confirmed = False
        db.log_event("INFO", "MODE_SWITCH", f"Switched trading mode to {mode.upper()}")

    return {"success": True, "trading_mode": settings.trading_mode.upper(), "live_confirmed": settings.live_trading_confirmed}


@api_router.post("/control/close_position")
def close_open_position(position_id: str):
    res = executor.close_position(position_id, exit_reason="MANUAL_CLOSE")
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


# 4. Positions & Orders
@api_router.get("/positions")
def get_positions():
    return {
        "open_positions": list(executor.active_positions.values()),
        "all_db_positions": db.get_open_positions(trading_mode=settings.trading_mode),
    }


@api_router.get("/orders")
def get_orders(limit: int = 100):
    return {
        "orders": db.get_orders(limit=limit, trading_mode=settings.trading_mode)
    }


@api_router.post("/orders/cancel")
def cancel_order(order_id: str):
    res = exchange_client.cancel_order(order_id)
    return res


# 5. Trade History & CSV Export
@api_router.get("/trades")
def get_trade_history(limit: int = 200):
    return {
        "trades": db.get_trades(limit=limit, trading_mode=settings.trading_mode)
    }


@api_router.get("/trades/export_csv")
def export_trade_history_csv():
    trades = db.get_trades(limit=1000, trading_mode=settings.trading_mode)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "trade_id", "symbol", "side", "entry_time", "exit_time", "entry_price",
        "exit_price", "stop_price", "target_price", "exit_reason", "bars_held",
        "quantity", "notional", "gross_pnl", "fees", "slippage", "net_pnl",
        "realised_r", "trading_mode"
    ])
    for t in trades:
        writer.writerow([
            t["trade_id"], t["symbol"], t["side"], t["entry_time"], t["exit_time"],
            t["entry_price"], t["exit_price"], t["stop_price"], t["target_price"],
            t["exit_reason"], t["bars_held"], t["quantity"], t["notional"],
            t["gross_pnl"], t["fees"], t["slippage"], t["net_pnl"], t["realised_r"],
            t["trading_mode"]
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades_export.csv"}
    )


# 6. Strategy Configuration
@api_router.get("/strategy/config")
def get_strategy_config():
    return {
        "default_symbol": settings.default_symbol,
        "timeframe": settings.timeframe,
        "ema_fast_period": settings.ema_fast_period,
        "ema_slow_period": settings.ema_slow_period,
        "atr_period": settings.atr_period,
        "vol_ma_period": settings.vol_ma_period,
        "vol_trigger_multiplier": settings.vol_trigger_multiplier,
        "pullback_tolerance": settings.pullback_tolerance,
        "stop_atr_multiplier": settings.stop_atr_multiplier,
        "min_stop_pct": settings.min_stop_pct,
        "max_stop_pct": settings.max_stop_pct,
        "take_profit_rr": settings.take_profit_rr,
        "max_hold_bars": settings.max_hold_bars,
        "session_start_hour": settings.session_start_hour,
        "session_end_hour": settings.session_end_hour,
        "risk_pct_per_trade": settings.risk_pct_per_trade,
        "max_leverage": settings.max_leverage,
        "daily_loss_limit_pct": settings.daily_loss_limit_pct,
        "cooldown_bars": settings.cooldown_bars,
        "max_open_positions": settings.max_open_positions,
        "slippage_rate": settings.slippage_rate,
        "fixed_spread": settings.fixed_spread,
    }


@api_router.post("/strategy/config")
def update_strategy_config(cfg: StrategyConfigModel):
    for field, val in cfg.model_dump(exclude_unset=True).items():
        if hasattr(settings, field) and val is not None:
            setattr(settings, field, val)
    db.log_event("INFO", "CONFIG_UPDATE", "Strategy parameters updated.", cfg.model_dump(exclude_unset=True))
    return {"success": True, "message": "Strategy configuration updated."}


# 7. System Logs
@api_router.get("/logs")
def get_logs(limit: int = 100, level: Optional[str] = None):
    return {"logs": db.get_recent_logs(limit=limit, level=level)}


# 8. Signals
@api_router.get("/signals")
def get_signals(limit: int = 50):
    return {"signals": db.get_signals(limit=limit)}


# 9. Equity Curve History
@api_router.get("/analytics/equity")
def get_equity_history():
    hist = db.get_equity_history(limit=500, trading_mode=settings.trading_mode)
    return {"equity_history": hist}


# 10. Run Backtest On Demand
@api_router.post("/backtest/run")
def trigger_backtest():
    try:
        summary = run_full_evaluation()
        return {"success": True, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/backtest/report")
def get_backtest_report():
    report_file = str(RESULTS_DIR / "REPORT.md")
    if os.path.exists(report_file):
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {"report_markdown": content}
    return {"report_markdown": "Report not yet generated. Run backtest first."}


# 11. Settings & Credentials
@api_router.post("/settings/credentials")
def update_credentials(creds: CredentialsModel):
    if creds.api_key:
        settings.coindcx_api_key = creds.api_key
        exchange_client.api_key = creds.api_key
    if creds.api_secret:
        settings.coindcx_api_secret = creds.api_secret
        exchange_client.api_secret = creds.api_secret
    if creds.telegram_bot_token:
        settings.telegram_bot_token = creds.telegram_bot_token
    if creds.telegram_chat_id:
        settings.telegram_chat_id = creds.telegram_chat_id
    db.log_event("INFO", "AUTH_UPDATE", "API credentials updated safely (masked).")
    return {"success": True, "message": "Credentials updated successfully."}
