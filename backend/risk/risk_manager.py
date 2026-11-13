"""
Independent Risk Management Engine.
Enforces capital exposure limits, position sizing, max leverage, daily loss halts,
drawdown limits, and circuit breakers. Operates with autonomous authority over entries.
"""
import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import pandas as pd
from backend.config.settings import settings
from backend.database.db import db


class RiskManager:
    def __init__(self):
        self.emergency_halt = False
        self.start_of_day_equity = settings.starting_equity
        self.current_ist_day = None
        self.daily_realised_pnl = 0.0
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.last_trade_closed_time = 0
        self.max_daily_trades = 20
        self.max_consecutive_losses_limit = 5
        self.max_account_drawdown_pct = 20.0  # protective circuit breaker

    def _update_daily_tracking(self, current_equity: float):
        # IST is UTC + 5h 30m
        now_ist_date = (pd.to_datetime(datetime.utcnow()) + pd.Timedelta(hours=5, minutes=30)).date()
        if self.current_ist_day != now_ist_date:
            self.current_ist_day = now_ist_date
            self.start_of_day_equity = current_equity
            self.daily_realised_pnl = 0.0
            self.daily_trade_count = 0
            db.log_event("INFO", "RISK_DAILY_RESET", f"IST day reset to {now_ist_date}. Start equity: ${current_equity:.2f}")

    def validate_entry_signal(
        self,
        signal: Dict[str, Any],
        current_equity: float,
        open_positions_count: int,
        market_price: float,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Validates signal against all risk parameters.
        Returns:
            passed: bool
            rejection_reason: str or None
            calculated_size: float (contracts/BTC)
        """
        self._update_daily_tracking(current_equity)

        # 1. Emergency Halt Check
        if self.emergency_halt:
            return False, "REJECTED_EMERGENCY_HALT_ACTIVE", 0.0

        # 2. Maximum Open Positions (Max 1)
        if open_positions_count >= settings.max_open_positions:
            return False, "REJECTED_MAX_OPEN_POSITIONS_REACHED", 0.0

        # 3. Daily Loss Halt (-2% of start of day equity)
        max_daily_loss = self.start_of_day_equity * settings.daily_loss_limit_pct
        if self.daily_realised_pnl <= -max_daily_loss:
            return False, f"REJECTED_DAILY_LOSS_HALT_REACHED (-${abs(self.daily_realised_pnl):.2f})", 0.0

        # 4. Maximum Account Drawdown Protection
        if current_equity < settings.starting_equity * (1.0 - (self.max_account_drawdown_pct / 100.0)):
            self.emergency_halt = True
            return False, "REJECTED_MAX_DRAWDOWN_CIRCUIT_BREAKER", 0.0

        # 5. Consecutive Losses Limit
        if self.consecutive_losses >= self.max_consecutive_losses_limit:
            return False, f"REJECTED_MAX_CONSECUTIVE_LOSSES ({self.consecutive_losses})", 0.0

        # 6. Cooldown Check (15 minutes after trade close)
        cooldown_seconds = settings.cooldown_bars * 300  # 3 bars * 5m = 900s
        if time.time() - self.last_trade_closed_time < cooldown_seconds:
            remaining = int(cooldown_seconds - (time.time() - self.last_trade_closed_time))
            return False, f"REJECTED_COOLDOWN_ACTIVE ({remaining}s remaining)", 0.0

        # 7. Sizing & Leverage Validation
        stop_dist = signal.get("stop_distance", 0.0)
        if stop_dist <= 0:
            return False, "REJECTED_INVALID_STOP_DISTANCE", 0.0

        # Stop boundaries: 0.20% floor, 0.35% cap
        stop_pct = stop_dist / market_price
        if stop_pct > settings.max_stop_pct:
            return False, f"REJECTED_STOP_EXCEEDS_CAP ({stop_pct*100:.3f}% > {settings.max_stop_pct*100:.2f}%)", 0.0

        # Risk amount: 0.5% of current equity
        risk_amount_usd = current_equity * settings.risk_pct_per_trade
        raw_size = risk_amount_usd / stop_dist
        notional = raw_size * market_price
        max_notional = current_equity * settings.max_leverage

        # Clamp size to max leverage
        effective_size = raw_size
        if notional > max_notional:
            effective_size = max_notional / market_price

        # Minimum quantity check (e.g. 0.001 BTC)
        if effective_size < 0.0001:
            return False, "REJECTED_ORDER_SIZE_BELOW_MINIMUM", 0.0

        return True, None, effective_size

    def record_trade_completion(self, net_pnl: float):
        """
        Updates internal risk metrics upon trade exit.
        """
        self.last_trade_closed_time = time.time()
        self.daily_realised_pnl += net_pnl
        self.daily_trade_count += 1
        
        if net_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def trigger_emergency_stop(self):
        self.emergency_halt = True
        db.log_event("CRITICAL", "RISK_EMERGENCY_STOP", "Emergency stop triggered. New entries halted immediately.")

    def resume_trading(self):
        self.emergency_halt = False
        db.log_event("INFO", "RISK_RESUME", "Trading resumed by user.")


# Global risk manager instance
risk_manager = RiskManager()
