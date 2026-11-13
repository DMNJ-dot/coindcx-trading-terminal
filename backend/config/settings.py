"""
Application Configuration and Environment Settings.
Secure credential handling — never expose API secrets in responses or logs.
Uses OS-independent paths so the application runs identically on Windows and Linux cloud hosts.
"""
from pathlib import Path
from typing import Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"


class AppSettings(BaseSettings):
    # Operating Mode: 'backtest', 'paper', 'testnet', 'live'
    trading_mode: str = "paper"
    live_trading_confirmed: bool = False

    # Optional Web Access Protection (recommended when hosted on a public URL)
    dashboard_username: str = "admin"
    dashboard_password: str = ""

    # CoinDCX Credentials
    coindcx_api_key: str = ""
    coindcx_api_secret: str = ""
    coindcx_base_url: str = "https://api.coindcx.com"
    coindcx_public_url: str = "https://public.coindcx.com"
    coindcx_ws_url: str = "wss://stream.coindcx.com"

    # Target Instrument
    default_symbol: str = "B-BTC_USDT"
    timeframe: str = "5m"

    # Risk Parameters
    starting_equity: float = 10000.0
    risk_pct_per_trade: float = 0.005  # 0.5%
    max_leverage: float = 10.0
    daily_loss_limit_pct: float = 0.02  # 2.0%
    cooldown_bars: int = 3  # 15 minutes
    max_hold_bars: int = 6  # 30 minutes
    max_open_positions: int = 1
    slippage_rate: float = 0.0003  # 0.03% round-trip
    fixed_spread: float = 0.50

    # Strategy Parameters
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    atr_period: int = 14
    vol_ma_period: int = 20
    vol_trigger_multiplier: float = 0.8
    pullback_tolerance: float = 0.0005  # 0.05%
    stop_atr_multiplier: float = 0.25
    min_stop_pct: float = 0.0020  # 0.20%
    max_stop_pct: float = 0.0035  # 0.35%
    take_profit_rr: float = 3.0
    session_start_hour: float = 7.5   # 07:30 UTC = 13:00 IST
    session_end_hour: float = 16.5    # 16:30 UTC = 22:00 IST

    # Telegram Notifications
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    notifications_enabled: bool = False

    # Server & Storage
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "8000"))
    db_path: str = str(BASE_DIR / "coindcx_terminal.db")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Global settings singleton
settings = AppSettings()
