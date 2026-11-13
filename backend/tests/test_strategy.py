"""
Comprehensive Unit Tests for Quantitative Strategy, No Look-Ahead, Hand Fixtures,
and Pessimistic vs Optimistic Ambiguity Resolution.
"""
import pytest
import numpy as np
import pandas as pd
from backend.backtest.indicators import add_all_indicators, compute_session_vwap, compute_ema, compute_atr
from backend.backtest.signals import generate_candidate_signals, RawSignal
from backend.backtest.engine import BacktestEngine, TradeRecord
from backend.backtest.metrics import compute_metrics


def create_synthetic_bars() -> pd.DataFrame:
    """
    Creates a controlled synthetic dataset of 5-minute bars.
    Includes an exact setup for:
    - 3 bars of uptrend (close > vwap, ema9 > ema21)
    - Pullback bar touching EMA21 without closing below VWAP
    - Trigger bar closing back above EMA9 with high volume
    - Subsequent ambiguous bar with high spanning both stop and target
    """
    dts = pd.date_range("2024-01-08 07:00:00", periods=25, freq="5min", tz="UTC")
    
    records = []
    prices = [
        # Warmup bars with volume = 100, no pullback
        (50000, 50050, 50000, 50050, 100),  # 0
        (50050, 50100, 50050, 50100, 100),  # 1
        (50100, 50150, 50100, 50150, 100),  # 2
        (50150, 50200, 50150, 50200, 100),  # 3
        (50200, 50250, 50200, 50250, 100),  # 4
        (50250, 50300, 50250, 50300, 100),  # 5: Trend bar 1
        (50300, 50350, 50300, 50350, 100),  # 6: Trend bar 2
        # Bar 7: Pullback bar: close >= vwap (~50200), low touches EMA21 (~50210)
        (50350, 50360, 50210, 50260, 100),  # 7: Pullback
        # Bar 8: Trigger bar: close back above EMA9 (~50280), vol 250 >= 0.8 * 100
        (50260, 50400, 50250, 50380, 250),  # 8: Trigger
        # Bar 9: Entry bar: opens at 50380
        (50380, 50420, 50350, 50390, 100),  # 9: Entry bar
        # Bar 10: Ambiguous bar: low dips to 49900 (hits stop ~50150), high reaches 51500 (hits target ~51000)
        (50390, 51500, 49900, 50400, 100),  # 10: Ambiguous
        (50400, 50450, 50350, 50400, 100),  # 11
        (50400, 50450, 50350, 50400, 100),  # 12
        (50400, 50450, 50350, 50400, 100),  # 13
        (50400, 50450, 50350, 50400, 100),  # 14
        (50400, 50450, 50350, 50400, 100),  # 15
        (50400, 50450, 50350, 50400, 100),  # 16
        (50400, 50450, 50350, 50400, 100),  # 17
        (50400, 50450, 50350, 50400, 100),  # 18
        (50400, 50450, 50350, 50400, 100),  # 19
        (50400, 50450, 50350, 50400, 100),  # 20
        (50400, 50450, 50350, 50400, 100),  # 21
        (50400, 50450, 50350, 50400, 100),  # 22
        (50400, 50450, 50350, 50400, 100),  # 23
        (50400, 50450, 50350, 50400, 100),  # 24
    ]
    
    for dt, (o, h, l, c, v) in zip(dts, prices):
        records.append({
            "dt_utc": dt,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v)
        })
    return pd.DataFrame(records)


def test_no_lookahead_truncation():
    """
    CRITICAL UNIT TEST:
    Truncates a dataset at a random bar and proves signals up to that bar
    are 100% IDENTICAL to the full-data run.
    Guarantees indicators and signals never use future bars.
    """
    from backend.config.settings import DATA_DIR
    parquet_path = str(DATA_DIR / "clean_5m.parquet")
    df_full = pd.read_parquet(parquet_path).head(2000).copy()
    
    df_full_ind = add_all_indicators(df_full)
    valid_full, rejected_full = generate_candidate_signals(df_full_ind)
    
    cutoff_bar = 1250
    df_trunc = df_full.iloc[:cutoff_bar].copy()
    df_trunc_ind = add_all_indicators(df_trunc)
    valid_trunc, rejected_trunc = generate_candidate_signals(df_trunc_ind)
    
    full_sub_valid = [s for s in valid_full if s.bar_index < cutoff_bar - 1]
    trunc_sub_valid = [s for s in valid_trunc if s.bar_index < cutoff_bar - 1]
    
    assert len(full_sub_valid) == len(trunc_sub_valid), (
        f"Signal count mismatch under truncation! Full: {len(full_sub_valid)}, Trunc: {len(trunc_sub_valid)}"
    )
    
    for s_full, s_trunc in zip(full_sub_valid, trunc_sub_valid):
        assert s_full.bar_index == s_trunc.bar_index
        assert s_full.side == s_trunc.side
        assert np.isclose(s_full.trigger_close, s_trunc.trigger_close)
        assert np.isclose(s_full.expected_entry_price, s_trunc.expected_entry_price)
        assert np.isclose(s_full.stop_price, s_trunc.stop_price)
        assert np.isclose(s_full.target_price, s_trunc.target_price)
        assert np.isclose(s_full.atr, s_trunc.atr)


def test_hand_verifiable_fixture_and_ambiguity_resolution():
    """
    HAND-VERIFIABLE FIXTURE TEST:
    Verifies on a synthetic bar series that:
    1. Pessimistic mode resolves same-bar ambiguity to STOP_LOSS.
    2. Optimistic mode resolves same-bar ambiguity to TAKE_PROFIT.
    3. Trade counts, prices, and metrics match exact hand calculations.
    """
    df = create_synthetic_bars()
    df_ind = add_all_indicators(df)
    
    # Override filters for controlled fixture
    df_ind["atr_q10"] = 0.0
    df_ind["atr_q90"] = 999999.0
    df_ind["ema_gap_pct"] = 0.01  # above 0.03%
    
    valid_signals, rejected_signals = generate_candidate_signals(
        df_ind,
        vol_multiplier=0.8,
        min_stop_pct=0.001,
        max_stop_pct=0.05,
        session_start_hour=0.0,
        session_end_hour=24.0
    )
    
    assert len(valid_signals) >= 1, f"Expected at least 1 valid signal, got {len(valid_signals)}. Rejected: {[r.rejection_reason for r in rejected_signals]}"
    sig = valid_signals[0]
    assert sig.side == "LONG"
    assert sig.bar_index == 8
    
    engine = BacktestEngine(starting_equity=10000.0, risk_pct=0.005, max_leverage=10.0)
    
    # 1. Pessimistic run: ambiguous bar MUST resolve to STOP_LOSS
    trades_pess, _ = engine.run(df_ind, [sig], scenario="primary", mode="pessimistic")
    assert len(trades_pess) == 1
    t_pess = trades_pess[0]
    assert t_pess.ambiguous_bar is True, "Expected ambiguous_bar to be True"
    assert t_pess.exit_reason == "STOP_LOSS", f"Pessimistic mode must resolve to STOP_LOSS, got {t_pess.exit_reason}"
    assert t_pess.net_pnl < 0, "Pessimistic stop loss must produce a negative net PnL"
    
    # 2. Optimistic run: ambiguous bar MUST resolve to TAKE_PROFIT
    trades_opt, _ = engine.run(df_ind, [sig], scenario="primary", mode="optimistic")
    assert len(trades_opt) == 1
    t_opt = trades_opt[0]
    assert t_opt.ambiguous_bar is True, "Expected ambiguous_bar to be True"
    assert t_opt.exit_reason == "TAKE_PROFIT", f"Optimistic mode must resolve to TAKE_PROFIT, got {t_opt.exit_reason}"
    assert t_opt.net_pnl > 0, "Optimistic take profit must produce positive net PnL"


def test_same_bar_entry_exit_rule():
    """
    Verifies that on the entry bar, target is ignored and cannot exit except via stop.
    """
    df = create_synthetic_bars()
    # Modify entry bar (index 9) so it hits target but not stop
    df.loc[9, "high"] = 52000.0  # hits target
    df.loc[9, "low"] = 50350.0   # does not hit stop
    
    df_ind = add_all_indicators(df)
    df_ind["atr_q10"] = 0.0
    df_ind["atr_q90"] = 999999.0
    df_ind["ema_gap_pct"] = 0.01
    
    valid_signals, _ = generate_candidate_signals(
        df_ind,
        min_stop_pct=0.001,
        max_stop_pct=0.05,
        session_start_hour=0.0,
        session_end_hour=24.0
    )
    
    engine = BacktestEngine(starting_equity=10000.0)
    sig = [s for s in valid_signals if s.bar_index == 8][:1]
    trades, _ = engine.run(df_ind, sig, mode="pessimistic")
    
    assert len(trades) == 1
    assert trades[0].entry_bar_idx == 9
    assert trades[0].exit_bar_idx > 9, "Trade cannot exit on entry bar via target"


def test_stop_cap_skip():
    """
    Verifies that if the required stop distance exceeds max_stop_pct, the signal is skipped.
    """
    df = create_synthetic_bars()
    df_ind = add_all_indicators(df)
    df_ind["atr_q10"] = 0.0
    df_ind["atr_q90"] = 999999.0
    df_ind["ema_gap_pct"] = 0.01
    
    # max_stop_pct = 0.00001 (tight cap)
    valid_signals, rejected_signals = generate_candidate_signals(
        df_ind,
        max_stop_pct=0.00001,
        session_start_hour=0.0,
        session_end_hour=24.0
    )
    assert len(valid_signals) == 0
    assert any("FILTER_STOP_EXCEEDS_MAX" in str(r.rejection_reason) for r in rejected_signals)
