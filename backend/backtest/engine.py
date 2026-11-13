"""
High-Performance Backtesting Engine for VWAP + EMA Trend Pullback Strategy.
Supports Pessimistic (headline) and Optimistic resolution for same-bar stop/target.
Implements compounding equity, sizing (0.5% risk, max 10x leverage), cooldown, daily loss halt.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from backend.backtest.signals import RawSignal


@dataclass
class TradeRecord:
    trade_id: int
    entry_bar_idx: int
    exit_bar_idx: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_reason: str  # 'STOP_LOSS', 'TAKE_PROFIT', 'TIME_STOP'
    bars_held: int
    size: float
    notional: float
    gross_pnl: float
    fees: float
    slippage: float
    net_pnl: float
    realised_r: float
    ambiguous_bar: bool
    equity_after: float


class BacktestEngine:
    def __init__(
        self,
        starting_equity: float = 10000.0,
        risk_pct: float = 0.005,
        max_leverage: float = 10.0,
        daily_loss_limit_pct: float = 0.02,
        cooldown_bars: int = 3,
        max_hold_bars: int = 6,
        slippage_rate: float = 0.0003,  # 0.03% round-trip default
    ):
        self.starting_equity = starting_equity
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.cooldown_bars = cooldown_bars
        self.max_hold_bars = max_hold_bars
        self.slippage_rate = slippage_rate

    def run(
        self,
        df: pd.DataFrame,
        signals: List[RawSignal],
        scenario: str = "primary",  # 'primary', 'scalper', 'maker'
        mode: str = "pessimistic",  # 'pessimistic' (headline) or 'optimistic'
        slippage_multiplier: float = 1.0,
    ) -> Tuple[List[TradeRecord], List[RawSignal]]:
        """
        Executes backtest over precomputed candidates against actual 5m bars.
        Returns:
            trades: List of executed TradeRecord
            skipped_signals: List of signals rejected at runtime (position open, cooldown, daily halt)
        """
        # Fee structure setup
        # CoinDCX: Taker 0.05%, Maker 0.02%, GST 18% (* 1.18)
        gst = 1.18
        if scenario == "primary":
            entry_fee_rate = 0.0005 * gst  # 0.059%
            exit_fee_rate = 0.0005 * gst   # 0.059%
        elif scenario == "scalper":
            entry_fee_rate = 0.0005 * gst  # 0.059%
            exit_fee_rate = 0.0            # 0% exit under 30m
        elif scenario == "maker":
            entry_fee_rate = 0.0002 * gst  # 0.0236%
            exit_fee_rate = 0.0005 * gst   # 0.059%
        else:
            raise ValueError(f"Unknown scenario: {scenario}")

        effective_slippage_rate = self.slippage_rate * slippage_multiplier
        half_slippage = effective_slippage_rate / 2.0

        equity = self.starting_equity
        trades: List[TradeRecord] = []
        runtime_skipped: List[RawSignal] = []

        # Pre-extract numpy series for speed
        n_bars = len(df)
        dts = df["dt_utc"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        
        # Precompute IST dates for daily loss tracking (IST = UTC + 5h30m)
        ist_dates = (pd.to_datetime(dts) + pd.Timedelta(hours=5, minutes=30)).date

        last_exit_bar = -9999
        current_ist_day = None
        sod_equity = equity
        daily_realised_pnl = 0.0

        # Create quick map of signals by bar_index
        signal_map = {sig.bar_index: sig for sig in signals}
        sorted_signal_bars = sorted(signal_map.keys())

        trade_id = 1
        pos_active_until_bar = -1

        for trigger_bar_idx in sorted_signal_bars:
            sig = signal_map[trigger_bar_idx]
            entry_bar_idx = trigger_bar_idx + 1

            if entry_bar_idx >= n_bars:
                continue

            entry_dt = pd.Timestamp(dts[entry_bar_idx])
            ist_day = ist_dates[entry_bar_idx]

            # Day transition check for Daily Loss Halt
            if ist_day != current_ist_day:
                current_ist_day = ist_day
                sod_equity = equity
                daily_realised_pnl = 0.0

            # Filter: Daily loss halt (reached -2% of start of day equity)
            if daily_realised_pnl <= -self.daily_loss_limit_pct * sod_equity:
                sig.rejection_reason = "FILTER_DAILY_LOSS_HALT"
                runtime_skipped.append(sig)
                continue

            # Filter: Position already open
            if entry_bar_idx <= pos_active_until_bar:
                sig.rejection_reason = "FILTER_POSITION_ALREADY_OPEN"
                runtime_skipped.append(sig)
                continue

            # Filter: Cooldown (15 min = 3 bars after any trade closes)
            if entry_bar_idx <= last_exit_bar + self.cooldown_bars:
                sig.rejection_reason = "FILTER_COOLDOWN_ACTIVE"
                runtime_skipped.append(sig)
                continue

            # Sizing calculation
            risk_usd = equity * self.risk_pct
            entry_price = opens[entry_bar_idx]
            stop_dist = sig.stop_distance
            stop_price = sig.stop_price
            target_price = sig.target_price

            size = risk_usd / stop_dist
            notional = size * entry_price
            max_notional = equity * self.max_leverage

            if notional > max_notional:
                size = max_notional / entry_price
                notional = max_notional

            # Simulate trade execution forward across max 6 bars
            # Bars: entry_bar_idx to entry_bar_idx + 5
            max_exit_bar = min(entry_bar_idx + self.max_hold_bars - 1, n_bars - 1)
            exit_bar_idx = max_exit_bar
            exit_price = closes[max_exit_bar]
            exit_reason = "TIME_STOP"
            is_ambiguous = False

            for b in range(entry_bar_idx, max_exit_bar + 1):
                b_high = highs[b]
                b_low = lows[b]
                b_close = closes[b]

                if sig.side == "LONG":
                    hit_stop = b_low <= stop_price
                    hit_target = b_high >= target_price

                    # Same-bar entry/exit rule:
                    # On entry bar, cannot exit except via stop
                    if b == entry_bar_idx:
                        if hit_stop:
                            exit_bar_idx = b
                            exit_price = stop_price
                            exit_reason = "STOP_LOSS"
                            break
                        # Target hit on entry bar is ignored per rule
                    else:
                        # Subsequent bars
                        if hit_stop and hit_target:
                            is_ambiguous = True
                            exit_bar_idx = b
                            if mode == "pessimistic":
                                exit_price = stop_price
                                exit_reason = "STOP_LOSS"
                            else:
                                exit_price = target_price
                                exit_reason = "TAKE_PROFIT"
                            break
                        elif hit_stop:
                            exit_bar_idx = b
                            exit_price = stop_price
                            exit_reason = "STOP_LOSS"
                            break
                        elif hit_target:
                            exit_bar_idx = b
                            exit_price = target_price
                            exit_reason = "TAKE_PROFIT"
                            break

                else:  # SHORT
                    hit_stop = b_high >= stop_price
                    hit_target = b_low <= target_price

                    if b == entry_bar_idx:
                        if hit_stop:
                            exit_bar_idx = b
                            exit_price = stop_price
                            exit_reason = "STOP_LOSS"
                            break
                    else:
                        if hit_stop and hit_target:
                            is_ambiguous = True
                            exit_bar_idx = b
                            if mode == "pessimistic":
                                exit_price = stop_price
                                exit_reason = "STOP_LOSS"
                            else:
                                exit_price = target_price
                                exit_reason = "TAKE_PROFIT"
                            break
                        elif hit_stop:
                            exit_bar_idx = b
                            exit_price = stop_price
                            exit_reason = "STOP_LOSS"
                            break
                        elif hit_target:
                            exit_bar_idx = b
                            exit_price = target_price
                            exit_reason = "TAKE_PROFIT"
                            break

            # Calculate P&L and fees
            exit_notional = size * exit_price
            if sig.side == "LONG":
                gross_pnl = size * (exit_price - entry_price)
            else:
                gross_pnl = size * (entry_price - exit_price)

            fee_entry = notional * entry_fee_rate
            fee_exit = exit_notional * exit_fee_rate
            total_fees = fee_entry + fee_exit

            slip_cost = (notional * half_slippage) + (exit_notional * half_slippage)
            net_pnl = gross_pnl - total_fees - slip_cost
            realised_r = net_pnl / (size * stop_dist) if (size * stop_dist) > 0 else 0.0

            equity += net_pnl
            daily_realised_pnl += net_pnl
            last_exit_bar = exit_bar_idx
            pos_active_until_bar = exit_bar_idx

            bars_held = (exit_bar_idx - entry_bar_idx) + 1
            exit_time = pd.Timestamp(dts[exit_bar_idx])

            record = TradeRecord(
                trade_id=trade_id,
                entry_bar_idx=entry_bar_idx,
                exit_bar_idx=exit_bar_idx,
                entry_time=entry_dt,
                exit_time=exit_time,
                side=sig.side,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                exit_price=exit_price,
                exit_reason=exit_reason,
                bars_held=bars_held,
                size=size,
                notional=notional,
                gross_pnl=gross_pnl,
                fees=total_fees,
                slippage=slip_cost,
                net_pnl=net_pnl,
                realised_r=realised_r,
                ambiguous_bar=is_ambiguous,
                equity_after=equity,
            )
            trades.append(record)
            trade_id += 1

        return trades, runtime_skipped
