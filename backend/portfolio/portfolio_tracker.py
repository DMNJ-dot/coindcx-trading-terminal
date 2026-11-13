"""
Portfolio Tracker & Account Performance Manager.
Maintains continuous real-time accounting of balances, equity, exposure, leverage,
realised/unrealised P&L, drawdown, and statistical ratios.
"""
import time
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from backend.config.settings import settings
from backend.database.db import db
from backend.exchange.coindcx_client import exchange_client


class PortfolioTracker:
    def __init__(self):
        self.starting_equity = settings.starting_equity
        self.current_equity = settings.starting_equity
        self.realised_pnl = 0.0
        self.unrealised_pnl = 0.0
        self.today_pnl = 0.0
        self.used_margin = 0.0
        self.available_balance = settings.starting_equity
        self.current_exposure = 0.0
        self.current_leverage = 0.0
        self.max_drawdown_usd = 0.0
        self.max_drawdown_pct = 0.0
        self.peak_equity = settings.starting_equity
        self._load_from_db()

    def _load_from_db(self):
        trades = db.get_trades(limit=1000, trading_mode=settings.trading_mode)
        if trades:
            total_net = sum(t["net_pnl"] for t in trades)
            self.realised_pnl = total_net
            self.current_equity = self.starting_equity + total_net
            self.available_balance = self.current_equity
            self.peak_equity = max(self.starting_equity, self.current_equity)

    def update_open_position_metrics(self, open_positions: List[Dict[str, Any]], current_price: float):
        total_unrealised = 0.0
        total_margin = 0.0
        total_notional = 0.0

        for pos in open_positions:
            qty = pos["quantity"]
            entry = pos["entry_price"]
            side = pos["side"].upper()
            
            if side == "LONG":
                u_pnl = qty * (current_price - entry)
            else:
                u_pnl = qty * (entry - current_price)
                
            notional = qty * current_price
            margin = notional / pos.get("leverage", 10.0)
            
            total_unrealised += u_pnl
            total_margin += margin
            total_notional += notional

        self.unrealised_pnl = total_unrealised
        self.used_margin = total_margin
        self.current_exposure = total_notional
        self.current_equity = self.starting_equity + self.realised_pnl + self.unrealised_pnl
        self.available_balance = max(0.0, self.current_equity - self.used_margin)
        self.current_leverage = (self.current_exposure / self.current_equity) if self.current_equity > 0 else 0.0

        # Update peak and drawdown
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        dd_usd = self.peak_equity - self.current_equity
        dd_pct = (dd_usd / self.peak_equity) * 100.0 if self.peak_equity > 0 else 0.0
        if dd_usd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd_usd
            self.max_drawdown_pct = dd_pct

    def record_realised_trade(self, net_pnl: float):
        self.realised_pnl += net_pnl
        self.today_pnl += net_pnl
        self.current_equity += net_pnl
        self.available_balance = self.current_equity - self.used_margin
        db.record_equity_snapshot(self.current_equity, self.unrealised_pnl, self.realised_pnl, settings.trading_mode)

    def get_account_overview(self) -> Dict[str, Any]:
        return {
            "total_balance": round(self.starting_equity + self.realised_pnl, 2),
            "available_balance": round(self.available_balance, 2),
            "used_margin": round(self.used_margin, 2),
            "current_equity": round(self.current_equity, 2),
            "unrealised_pnl": round(self.unrealised_pnl, 2),
            "realised_pnl": round(self.realised_pnl, 2),
            "today_pnl": round(self.today_pnl, 2),
            "overall_trading_pnl": round(self.realised_pnl + self.unrealised_pnl, 2),
            "current_account_exposure": round(self.current_exposure, 2),
            "current_leverage": round(self.current_leverage, 2),
            "maximum_drawdown_usd": round(self.max_drawdown_usd, 2),
            "maximum_drawdown_pct": round(self.max_drawdown_pct, 2),
            "trading_mode": settings.trading_mode.upper(),
        }

    def get_trading_statistics(self) -> Dict[str, Any]:
        trades = db.get_trades(limit=500, trading_mode=settings.trading_mode)
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "reward_to_risk": 3.0,
                "expectancy": 0.0,
                "max_consecutive_losses": 0,
                "avg_holding_time_minutes": 0.0,
                "today_trade_count": 0,
            }
            
        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] <= 0]
        n_wins = len(wins)
        n_losses = len(losses)
        n_total = len(trades)
        
        win_rate = (n_wins / n_total) * 100.0 if n_total > 0 else 0.0
        sum_wins = sum(t["net_pnl"] for t in wins)
        sum_losses = abs(sum(t["net_pnl"] for t in losses))
        profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else (999.0 if sum_wins > 0 else 0.0)
        
        avg_win = (sum_wins / n_wins) if n_wins > 0 else 0.0
        avg_loss = (sum_losses / n_losses) if n_losses > 0 else 0.0
        expectancy = sum(t["net_pnl"] for t in trades) / n_total if n_total > 0 else 0.0
        avg_bars = sum(t["bars_held"] for t in trades) / n_total if n_total > 0 else 0.0

        # Streak calculation
        loss_streak = 0
        max_streak = 0
        for t in reversed(trades):
            if t["net_pnl"] <= 0:
                loss_streak += 1
                if loss_streak > max_streak:
                    max_streak = loss_streak
            else:
                loss_streak = 0

        return {
            "total_trades": n_total,
            "winning_trades": n_wins,
            "losing_trades": n_losses,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "reward_to_risk": 3.0,
            "expectancy": round(expectancy, 2),
            "max_consecutive_losses": max_streak,
            "avg_holding_time_minutes": round(avg_bars * 5.0, 1),
            "today_trade_count": len([t for t in trades if t["entry_time"].startswith(time.strftime("%Y-%m-%d"))]),
        }


# Global portfolio tracker instance
portfolio_tracker = PortfolioTracker()
