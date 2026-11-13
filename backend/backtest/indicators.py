"""
Technical Indicators for VWAP + EMA Trend Pullback Strategy.
All indicators are strictly causal — computed only from historical data
up to and including the current closed bar. No future lookahead.
"""
from typing import Tuple
import numpy as np
import pandas as pd


def compute_session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Computes Session VWAP anchored to the UTC day (resets 00:00 UTC).
    Typical Price = (High + Low + Close) / 3
    VWAP = cumsum(Typical Price * Volume) / cumsum(Volume) per UTC date.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"]
    
    # Extract UTC date
    dates = df["dt_utc"].dt.date
    
    # Group cumulative sum per day
    cum_pv = pv.groupby(dates).cumsum()
    cum_vol = df["volume"].groupby(dates).cumsum()
    
    # Avoid division by zero
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap.ffill()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average on series (standard ewm with adjust=False).
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average True Range (ATR).
    TR = max(H - L, |H - C_prev|, |L - C_prev|)
    ATR = Wilder's RMA over `period`.
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Wilder's smoothing alpha = 1 / period
    atr = tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean()
    return atr


def compute_volume_ma(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Simple moving average of volume over `period` closed bars.
    """
    return series.rolling(window=period, min_periods=1).mean()


def compute_rolling_atr_percentile(atr_series: pd.Series, window_bars: int = 8640) -> pd.Series:
    """
    Computes the trailing percentile (0.0 to 1.0) of ATR(14) over `window_bars`
    (8640 bars = 30 days of 5m bars).
    Strictly causal rolling rank.
    """
    # Fast causal rolling percentile: (rank - 1) / (count - 1)
    # Using rolling rank
    def calc_pct(window):
        val = window[-1]
        return np.mean(window <= val)

    # Use rolling apply with raw numpy for efficiency
    # For large datasets, let's optimize:
    # A rolling quantile/rank over 8640 bars can be computed efficiently or with pandas
    return atr_series.rolling(window=window_bars, min_periods=max(288, window_bars // 10)).apply(calc_pct, raw=True)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all strategy indicators to a copy of the dataframe.
    """
    out = df.copy()
    if "dt_utc" not in out.columns:
        out["dt_utc"] = pd.to_datetime(out["timestamp"], utc=True)
        
    out["vwap"] = compute_session_vwap(out)
    out["ema9"] = compute_ema(out["close"], period=9)
    out["ema21"] = compute_ema(out["close"], period=21)
    out["atr14"] = compute_atr(out, period=14)
    out["vol_ma20"] = compute_volume_ma(out["volume"], period=20)
    
    # Calculate rolling ATR percentile (8640 bars = 30 days)
    # To keep vectorised speed high across 315,000 bars, we can compute rolling quantiles
    # 10th percentile and 90th percentile over trailing 8640 bars:
    out["atr_q10"] = out["atr14"].rolling(window=8640, min_periods=288).quantile(0.10)
    out["atr_q90"] = out["atr14"].rolling(window=8640, min_periods=288).quantile(0.90)
    
    # EMA gap as fraction of close price
    out["ema_gap_pct"] = (out["ema9"] - out["ema21"]).abs() / out["close"]
    
    return out
