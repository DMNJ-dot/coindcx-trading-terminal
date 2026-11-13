"""
Live Quantitative Strategy Engine.
Implements the exact VWAP + EMA Trend Pullback strategy on closed 5-minute candles,
validates with RiskManager, and dispatches to Executor.
"""
import time
import threading
import uuid
from typing import Dict, Any, Optional
import pandas as pd
from backend.config.settings import settings
from backend.database.db import db
from backend.market_data.stream_manager import market_data_manager
from backend.backtest.signals import generate_candidate_signals, RawSignal
from backend.risk.risk_manager import risk_manager
from backend.execution.executor import executor
from backend.portfolio.portfolio_tracker import portfolio_tracker
from backend.notifications.notifier import notifier
from backend.exchange.coindcx_client import exchange_client


class StrategyEngine:
    def __init__(self):
        self.is_running = False
        self.auto_trading_enabled = False
        self.strategy_enabled = True
        self.last_evaluated_candle_time = None
        self.last_signal_time = None
        self.last_executed_trade = None
        self.last_error = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if not self.is_running:
                self.is_running = True
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
                db.log_event("INFO", "STRATEGY_ENGINE", "Live Strategy Engine started.")
                notifier.send_alert("BOT_STARTED", "Live Strategy Engine has been started.")

    def stop(self):
        with self._lock:
            self.is_running = False
            db.log_event("INFO", "STRATEGY_ENGINE", "Live Strategy Engine stopped.")
            notifier.send_alert("BOT_STOPPED", "Live Strategy Engine has been stopped.")

    def set_auto_trading(self, enabled: bool):
        self.auto_trading_enabled = enabled
        status_text = "ENABLED" if enabled else "DISABLED"
        db.log_event("INFO", "CONTROL", f"Auto trading {status_text}.")
        notifier.send_alert(f"AUTO_TRADING_{status_text}", f"Automated execution is now {status_text}.")

    def _loop(self):
        while self.is_running:
            try:
                ticker = market_data_manager.get_latest_ticker()
                current_price = ticker["price"]

                # 1. Continuous Position Monitoring
                if current_price > 0:
                    executor.monitor_positions(current_price)

                # 2. Check for New Closed Candle
                candles_df = market_data_manager.candles_df
                if not candles_df.empty and len(candles_df) >= 30 and self.strategy_enabled:
                    last_closed_candle = candles_df.iloc[-2]  # Bar -2 is the completed closed candle
                    candle_dt = pd.Timestamp(last_closed_candle["dt_utc"])

                    if self.last_evaluated_candle_time != candle_dt:
                        self.last_evaluated_candle_time = candle_dt
                        # Inform executor a new bar has elapsed
                        executor.monitor_positions(current_price, is_new_bar=True)
                        
                        # Evaluate Strategy
                        self._evaluate_strategy(candles_df.iloc[:-1].copy())

            except Exception as e:
                self.last_error = str(e)
                db.log_event("ERROR", "STRATEGY_LOOP", f"Evaluation error: {e}")

            time.sleep(2)

    def _evaluate_strategy(self, closed_candles_df: pd.DataFrame):
        valid_signals, static_rejected = generate_candidate_signals(
            closed_candles_df,
            vol_multiplier=settings.vol_trigger_multiplier,
            atr_stop_multiplier=settings.stop_atr_multiplier,
            min_stop_pct=settings.min_stop_pct,
            max_stop_pct=settings.max_stop_pct,
            session_start_hour=settings.session_start_hour,
            session_end_hour=settings.session_end_hour,
            primary_cost_pct=settings.slippage_rate + (0.0005 * 1.18 * 2),
            fixed_spread=settings.fixed_spread,
        )

        # Log any static rejections
        for r in static_rejected[-2:]:
            db.log_event("INFO", "SIGNAL_STATIC_FILTER", f"Signal filtered: {r.rejection_reason}", {
                "side": r.side, "close": r.trigger_close
            })

        # Check if valid signal was triggered on the most recent bar
        n_bars = len(closed_candles_df)
        recent_signals = [s for s in valid_signals if s.bar_index == n_bars - 1]

        for sig in recent_signals:
            sig_id = f"sig_{uuid.uuid4().hex[:8]}"
            self.last_signal_time = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            
            sig_dict = {
                "signal_id": sig_id,
                "timestamp": self.last_signal_time,
                "symbol": settings.default_symbol,
                "side": sig.side,
                "trigger_close": sig.trigger_close,
                "expected_entry_price": sig.expected_entry_price,
                "stop_price": sig.stop_price,
                "target_price": sig.target_price,
                "stop_distance": sig.stop_distance,
                "status": "GENERATED",
            }

            db.log_event("INFO", "SIGNAL_GENERATED", f"Valid {sig.side} signal generated!", sig_dict)
            notifier.send_alert(
                "SIGNAL_GENERATED",
                f"New {sig.side} Opportunity on {settings.default_symbol}\nPrice: ${sig.expected_entry_price:.2f}\nStop: ${sig.stop_price:.2f} | Target: ${sig.target_price:.2f}"
            )

            # Check Auto Trading
            if not self.auto_trading_enabled:
                sig_dict["status"] = "REJECTED"
                sig_dict["rejection_reason"] = "AUTO_TRADING_DISABLED"
                db.save_signal(sig_dict)
                db.log_event("INFO", "SIGNAL_SKIPPED", "Auto-trading disabled; signal not executed.")
                continue

            # Independent Risk Check
            current_eq = portfolio_tracker.current_equity
            open_pos_count = len(executor.active_positions)
            passed, reject_reason, size = risk_manager.validate_entry_signal(
                signal=sig_dict,
                current_equity=current_eq,
                open_positions_count=open_pos_count,
                market_price=sig.expected_entry_price
            )

            if not passed:
                sig_dict["status"] = "REJECTED"
                sig_dict["rejection_reason"] = reject_reason
                db.save_signal(sig_dict)
                db.log_event("WARNING", "RISK_REJECTION", f"Risk manager rejected signal: {reject_reason}")
                continue

            # Execute Entry
            exec_res = executor.execute_entry(sig_dict, size)
            if exec_res.get("success"):
                sig_dict["status"] = "EXECUTED"
                self.last_executed_trade = f"{sig.side} {size:.4f} @ ${sig.expected_entry_price:.2f}"
            else:
                sig_dict["status"] = "REJECTED"
                sig_dict["rejection_reason"] = exec_res.get("error", "Execution failed")

            db.save_signal(sig_dict)

    def get_status(self) -> Dict[str, Any]:
        return {
            "bot_running": self.is_running,
            "auto_trading_enabled": self.auto_trading_enabled,
            "strategy_enabled": self.strategy_enabled,
            "exchange_connected": exchange_client.is_connected,
            "market_data_connected": market_data_manager.is_running,
            "trading_mode": settings.trading_mode.upper(),
            "live_confirmed": settings.live_trading_confirmed,
            "open_positions_count": len(executor.active_positions),
            "emergency_halt": risk_manager.emergency_halt,
            "last_signal_time": self.last_signal_time,
            "last_executed_trade": self.last_executed_trade,
            "last_error": self.last_error or exchange_client.last_error,
            "last_sync_time": exchange_client.last_sync_time,
        }


# Global strategy engine instance
strategy_engine = StrategyEngine()
