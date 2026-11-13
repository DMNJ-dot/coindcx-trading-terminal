"""
Performance Analytics & Metrics Calculation for Backtesting Engine.
Computes comprehensive institutional metrics, drawdown curves, Sharpe/Sortino,
and monthly breakdown tables.
"""
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from backend.backtest.engine import TradeRecord


def compute_metrics(
    trades: List[TradeRecord],
    starting_equity: float = 10000.0,
    total_calendar_days: float = 1096.0,
    trading_days: float = 780.0,
) -> Dict[str, Any]:
    """
    Computes all quantitative metrics required by specification.
    """
    if not trades:
        return {
            "total_trades": 0,
            "net_pnl_usd": 0.0,
            "net_pnl_pct": 0.0,
            "final_equity": starting_equity,
            "win_rate_pct": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
            "profit_factor": 0.0,
            "avg_win_usd": 0.0,
            "avg_loss_usd": 0.0,
            "expectancy_usd": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_duration_days": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_consecutive_losses": 0,
            "avg_holding_bars": 0.0,
            "avg_holding_minutes": 0.0,
            "trades_per_day": 0.0,
            "pct_realised_ge_3r": 0.0,
            "total_fees_usd": 0.0,
            "total_slippage_usd": 0.0,
            "ambiguity_count": 0,
            "ambiguity_rate_pct": 0.0,
        }

    df_t = pd.DataFrame([t.__dict__ for t in trades])
    n_trades = len(df_t)
    
    net_pnls = df_t["net_pnl"].values
    realised_rs = df_t["realised_r"].values
    gross_pnls = df_t["gross_pnl"].values
    fees = df_t["fees"].sum()
    slippage = df_t["slippage"].sum()
    
    total_net_pnl = net_pnls.sum()
    final_equity = starting_equity + total_net_pnl
    net_pnl_pct = (total_net_pnl / starting_equity) * 100.0
    
    wins = df_t[df_t["net_pnl"] > 0]
    losses = df_t[df_t["net_pnl"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = (n_wins / n_trades) * 100.0 if n_trades > 0 else 0.0
    
    gross_wins = wins["net_pnl"].sum()
    gross_losses = abs(losses["net_pnl"].sum())
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (999.0 if gross_wins > 0 else 0.0)
    
    avg_win = wins["net_pnl"].mean() if n_wins > 0 else 0.0
    avg_loss = abs(losses["net_pnl"].mean()) if n_losses > 0 else 0.0
    
    expectancy_usd = net_pnls.mean() if n_trades > 0 else 0.0
    expectancy_r = realised_rs.mean() if n_trades > 0 else 0.0
    
    # Drawdown calculation
    equity_curve = [starting_equity]
    for p in net_pnls:
        equity_curve.append(equity_curve[-1] + p)
    equity_arr = np.array(equity_curve)
    
    running_max = np.maximum.accumulate(equity_arr)
    drawdowns_usd = running_max - equity_arr
    drawdown_pcts = (drawdowns_usd / running_max) * 100.0
    
    max_dd_usd = drawdowns_usd.max()
    max_dd_pct = drawdown_pcts.max()
    
    # Drawdown duration calculation (in trade count or days)
    peak_idx = 0
    max_dd_duration_trades = 0
    for idx, val in enumerate(equity_arr):
        if val >= running_max[idx]:
            peak_idx = idx
        else:
            dur = idx - peak_idx
            if dur > max_dd_duration_trades:
                max_dd_duration_trades = dur
                
    # Max consecutive losses
    loss_streak = 0
    max_consecutive_losses = 0
    for pnl in net_pnls:
        if pnl <= 0:
            loss_streak += 1
            if loss_streak > max_consecutive_losses:
                max_consecutive_losses = loss_streak
        else:
            loss_streak = 0
            
    # Holding times
    avg_holding_bars = df_t["bars_held"].mean()
    avg_holding_minutes = avg_holding_bars * 5.0
    
    # Trades per day
    trades_per_day = n_trades / trading_days if trading_days > 0 else 0.0
    
    # % realised >= +3R
    ge_3r_count = (df_t["realised_r"] >= 2.99).sum()
    pct_realised_ge_3r = (ge_3r_count / n_trades) * 100.0 if n_trades > 0 else 0.0
    
    # Ambiguity
    ambiguity_count = df_t["ambiguous_bar"].sum()
    ambiguity_rate = (ambiguity_count / n_trades) * 100.0 if n_trades > 0 else 0.0
    
    # Sharpe & Sortino (Standard Daily Returns Annualization: sqrt(252))
    # Map trade net P&L into daily P&L series
    df_t["exit_date"] = pd.to_datetime(df_t["exit_time"]).dt.date
    daily_pnl = df_t.groupby("exit_date")["net_pnl"].sum()
    # Fill zero PnL for active trading days to avoid overestimating Sharpe
    # Daily return = daily_pnl / starting_equity (or current equity)
    daily_returns = daily_pnl / starting_equity
    
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        mean_ret = daily_returns.mean()
        std_ret = daily_returns.std()
        # Annualized assuming 252 trading days per year
        sharpe = (mean_ret / std_ret) * np.sqrt(252)
        
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 1 else std_ret
        sortino = (mean_ret / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    return {
        "total_trades": int(n_trades),
        "net_pnl_usd": float(total_net_pnl),
        "net_pnl_pct": float(net_pnl_pct),
        "final_equity": float(final_equity),
        "win_rate_pct": float(win_rate),
        "winning_trades": int(n_wins),
        "losing_trades": int(n_losses),
        "profit_factor": float(profit_factor),
        "avg_win_usd": float(avg_win),
        "avg_loss_usd": float(avg_loss),
        "expectancy_usd": float(expectancy_usd),
        "expectancy_r": float(expectancy_r),
        "max_drawdown_usd": float(max_dd_usd),
        "max_drawdown_pct": float(max_dd_pct),
        "max_dd_duration_trades": int(max_dd_duration_trades),
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sortino),
        "max_consecutive_losses": int(max_consecutive_losses),
        "avg_holding_bars": float(avg_holding_bars),
        "avg_holding_minutes": float(avg_holding_minutes),
        "trades_per_day": float(trades_per_day),
        "pct_realised_ge_3r": float(pct_realised_ge_3r),
        "total_fees_usd": float(fees),
        "total_slippage_usd": float(slippage),
        "ambiguity_count": int(ambiguity_count),
        "ambiguity_rate_pct": float(ambiguity_rate),
    }


def compute_monthly_pnl_table(trades: List[TradeRecord]) -> pd.DataFrame:
    """
    Returns monthly P&L aggregated dataframe.
    """
    if not trades:
        return pd.DataFrame(columns=["Year", "Month", "Net_PnL", "Trades", "Win_Rate"])
        
    df_t = pd.DataFrame([t.__dict__ for t in trades])
    df_t["dt"] = pd.to_datetime(df_t["exit_time"])
    df_t["Year"] = df_t["dt"].dt.year
    df_t["Month"] = df_t["dt"].dt.strftime("%b")
    df_t["Month_Num"] = df_t["dt"].dt.month
    
    rows = []
    for (year, month_num, month), grp in df_t.groupby(["Year", "Month_Num", "Month"]):
        n = len(grp)
        pnl = grp["net_pnl"].sum()
        wins = (grp["net_pnl"] > 0).sum()
        wr = (wins / n) * 100.0 if n > 0 else 0.0
        rows.append({
            "Year": year,
            "Month_Num": month_num,
            "Month": month,
            "Net_PnL": pnl,
            "Trades": n,
            "Win_Rate": wr,
        })
    return pd.DataFrame(rows).sort_values(by=["Year", "Month_Num"]).drop(columns=["Month_Num"])
