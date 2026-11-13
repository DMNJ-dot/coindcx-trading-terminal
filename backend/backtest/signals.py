"""
Signal Generation and No-Trade Filters for VWAP + EMA Trend Pullback Strategy.
Pure functions, strictly causal, no look-ahead.
Signals generated at trigger bar close; execution at NEXT bar's open.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import pandas as pd


@dataclass
class RawSignal:
    bar_index: int
    trigger_dt_utc: pd.Timestamp
    entry_dt_utc: pd.Timestamp
    side: str  # 'LONG' or 'SHORT'
    trigger_close: float
    expected_entry_price: float
    pullback_swing_price: float
    raw_stop_distance: float
    stop_distance: float
    stop_price: float
    target_price: float
    atr: float
    rejection_reason: Optional[str] = None


def is_session_active(dt: pd.Timestamp, session_start_hour: float = 7.5, session_end_hour: float = 16.5) -> bool:
    """
    Checks if bar is within trading window.
    Default: 13:00–22:00 IST = 07:30–16:30 UTC. Monday (0) through Friday (4) only.
    No weekend trading.
    """
    if dt.weekday() >= 5:  # Saturday or Sunday
        return False
    time_dec = dt.hour + dt.minute / 60.0
    return session_start_hour <= time_dec <= session_end_hour


def generate_candidate_signals(
    df: pd.DataFrame,
    vol_multiplier: float = 0.8,
    atr_stop_multiplier: float = 0.25,
    min_stop_pct: float = 0.0020,
    max_stop_pct: float = 0.0035,
    session_start_hour: float = 7.5,
    session_end_hour: float = 16.5,
    primary_cost_pct: float = 0.00148,
    fixed_spread: float = 0.50,
) -> Tuple[List[RawSignal], List[RawSignal]]:
    """
    Vectorized and pure scanning for candidate signals and rejected signals.
    Evaluates closed bars t-2, t-1, t.
    Returns:
        valid_signals: Signals that passed all strategy rules and static filters
        rejected_signals: Raw signals rejected with recorded reason
    """
    valid_signals: List[RawSignal] = []
    rejected_signals: List[RawSignal] = []
    
    n = len(df)
    if n < 5:
        return valid_signals, rejected_signals

    # Extract numpy arrays for high performance
    dts = df["dt_utc"].values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    volumes = df["volume"].values
    vwaps = df["vwap"].values
    ema9s = df["ema9"].values
    ema21s = df["ema21"].values
    atrs = df["atr14"].values
    vol_mas = df["vol_ma20"].values
    atr_q10s = df["atr_q10"].values
    atr_q90s = df["atr_q90"].values
    ema_gaps = df["ema_gap_pct"].values

    # Scan closed bars from index 2 to n-2 (since signal executes at index + 1)
    for i in range(2, n - 1):
        dt = pd.Timestamp(dts[i])
        
        # Check session window
        in_session = is_session_active(dt, session_start_hour, session_end_hour)
        if not in_session:
            continue
            
        c_i = closes[i]
        c_prev = closes[i - 1]
        c_prev2 = closes[i - 2]
        
        vw_i = vwaps[i]
        vw_prev = vwaps[i - 1]
        vw_prev2 = vwaps[i - 2]
        
        e9_i = ema9s[i]
        e9_prev = ema9s[i - 1]
        e9_prev2 = ema9s[i - 2]
        
        e21_i = ema21s[i]
        e21_prev = ema21s[i - 1]
        e21_prev2 = ema21s[i - 2]
        
        atr = atrs[i]
        vol_ma = vol_mas[i]
        if np.isnan(atr) or np.isnan(vol_ma) or not np.isfinite(atr):
            continue
        vol = volumes[i]
        next_open = opens[i + 1]
        next_dt = pd.Timestamp(dts[i + 1])
        
        # -----------------------------
        # LONG CONDITION CHECK
        # -----------------------------
        # 1. Trend for last 3 bars: close > vwap AND ema9 > ema21
        trend_long = (
            (c_i > vw_i and e9_i > e21_i) and
            (c_prev > vw_prev and e9_prev > e21_prev) and
            (c_prev2 > vw_prev2 and e9_prev2 > e21_prev2)
        )
        
        if trend_long:
            # 2. Pullback on bar i-1:
            # Touches within 0.05% of EMA21 or VWAP without closing below VWAP
            pullback_long = (
                (c_prev >= vw_prev) and
                (
                    (lows[i - 1] <= e21_prev * 1.0005) or
                    (lows[i - 1] <= vw_prev * 1.0005)
                )
            )
            
            # 3. Trigger on bar i:
            # Closes back above EMA9 AND volume >= vol_multiplier * 20-bar avg volume
            trigger_long = (
                (c_i > e9_i) and
                (vol >= vol_multiplier * vol_ma)
            )
            
            if pullback_long and trigger_long:
                # Stop loss calculation: beyond pullback swing low by atr_stop_multiplier * ATR
                swing_low = min(lows[i - 1], lows[i])
                raw_stop_dist = (next_open - swing_low) + (atr_stop_multiplier * atr)
                raw_stop_pct = raw_stop_dist / next_open
                
                # Check rejection filters
                rejection = None
                
                # Filter: ATR in top or bottom 10% trailing 30 days
                if atr > atr_q90s[i] or atr < atr_q10s[i]:
                    rejection = "FILTER_ATR_EXTREME_10PCT"
                # Filter: EMA gap < 0.03%
                elif ema_gaps[i] < 0.0003:
                    rejection = "FILTER_EMA_GAP_TOO_SMALL"
                # Filter: Required stop exceeds max_stop_pct (0.35%)
                elif raw_stop_pct > max_stop_pct:
                    rejection = f"FILTER_STOP_EXCEEDS_MAX_{max_stop_pct*100:.2f}PCT"
                else:
                    # Enforce floor 0.20%
                    effective_stop_dist = max(raw_stop_dist, min_stop_pct * next_open)
                    est_cost = (primary_cost_pct * next_open) + fixed_spread
                    # Filter: Estimated cost > 0.5 * stop distance
                    if est_cost > 0.5 * effective_stop_dist:
                        rejection = "FILTER_COST_EXCEEDS_HALF_STOP"
                
                # Compute prices
                effective_stop_dist = max(raw_stop_dist, min_stop_pct * next_open)
                stop_price = next_open - effective_stop_dist
                target_price = next_open + (3.0 * effective_stop_dist)
                
                sig = RawSignal(
                    bar_index=i,
                    trigger_dt_utc=dt,
                    entry_dt_utc=next_dt,
                    side="LONG",
                    trigger_close=c_i,
                    expected_entry_price=next_open,
                    pullback_swing_price=swing_low,
                    raw_stop_distance=raw_stop_dist,
                    stop_distance=effective_stop_dist,
                    stop_price=stop_price,
                    target_price=target_price,
                    atr=atr,
                    rejection_reason=rejection
                )
                
                if rejection is None:
                    valid_signals.append(sig)
                else:
                    rejected_signals.append(sig)
                continue  # One candidate per bar

        # -----------------------------
        # SHORT CONDITION CHECK (Exact Mirror)
        # -----------------------------
        trend_short = (
            (c_i < vw_i and e9_i < e21_i) and
            (c_prev < vw_prev and e9_prev < e21_prev) and
            (c_prev2 < vw_prev2 and e9_prev2 < e21_prev2)
        )
        
        if trend_short:
            pullback_short = (
                (c_prev <= vw_prev) and
                (
                    (highs[i - 1] >= e21_prev * 0.9995) or
                    (highs[i - 1] >= vw_prev * 0.9995)
                )
            )
            
            trigger_short = (
                (c_i < e9_i) and
                (vol >= vol_multiplier * vol_ma)
            )
            
            if pullback_short and trigger_short:
                swing_high = max(highs[i - 1], highs[i])
                raw_stop_dist = (swing_high - next_open) + (atr_stop_multiplier * atr)
                raw_stop_pct = raw_stop_dist / next_open
                
                rejection = None
                if atr > atr_q90s[i] or atr < atr_q10s[i]:
                    rejection = "FILTER_ATR_EXTREME_10PCT"
                elif ema_gaps[i] < 0.0003:
                    rejection = "FILTER_EMA_GAP_TOO_SMALL"
                elif raw_stop_pct > max_stop_pct:
                    rejection = f"FILTER_STOP_EXCEEDS_MAX_{max_stop_pct*100:.2f}PCT"
                else:
                    effective_stop_dist = max(raw_stop_dist, min_stop_pct * next_open)
                    est_cost = (primary_cost_pct * next_open) + fixed_spread
                    if est_cost > 0.5 * effective_stop_dist:
                        rejection = "FILTER_COST_EXCEEDS_HALF_STOP"
                
                effective_stop_dist = max(raw_stop_dist, min_stop_pct * next_open)
                stop_price = next_open + effective_stop_dist
                target_price = next_open - (3.0 * effective_stop_dist)
                
                sig = RawSignal(
                    bar_index=i,
                    trigger_dt_utc=dt,
                    entry_dt_utc=next_dt,
                    side="SHORT",
                    trigger_close=c_i,
                    expected_entry_price=next_open,
                    pullback_swing_price=swing_high,
                    raw_stop_distance=raw_stop_dist,
                    stop_distance=effective_stop_dist,
                    stop_price=stop_price,
                    target_price=target_price,
                    atr=atr,
                    rejection_reason=rejection
                )
                
                if rejection is None:
                    valid_signals.append(sig)
                else:
                    rejected_signals.append(sig)
                    
    return valid_signals, rejected_signals
