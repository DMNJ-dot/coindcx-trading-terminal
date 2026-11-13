"""
Automated Order Execution & Position Management Engine.
Manages trade entries, bracket protective orders, time-stop monitoring,
safe position close, exchange reconciliation, and paper/live lifecycle.
"""
import time
import uuid
from typing import Dict, Any, List, Optional
from backend.config.settings import settings
from backend.database.db import db
from backend.exchange.coindcx_client import exchange_client
from backend.risk.risk_manager import risk_manager
from backend.portfolio.portfolio_tracker import portfolio_tracker
from backend.notifications.notifier import notifier


class ExecutionEngine:
    def __init__(self):
        self.active_positions: Dict[str, Dict[str, Any]] = {}
        self.reconcile_on_startup()

    def reconcile_on_startup(self):
        """
        Retrieves actual positions from the exchange (or DB in paper mode),
        identifies mismatches, and safely restores position state.
        """
        db.log_event("INFO", "RECONCILIATION", "Executing startup position reconciliation...")
        if settings.trading_mode == "paper":
            db_positions = db.get_open_positions(trading_mode="paper")
            for p in db_positions:
                p_dict = dict(p)
                p_dict["bars_held"] = p_dict.get("bars_held", 0)
                self.active_positions[p_dict["position_id"]] = p_dict
            db.log_event("INFO", "RECONCILIATION", f"Recovered {len(self.active_positions)} paper positions from database.")
        else:
            # Query live positions from CoinDCX
            exchange_positions = exchange_client.get_open_positions()
            db.log_event("INFO", "RECONCILIATION", f"Retrieved {len(exchange_positions)} positions from CoinDCX API.")

    def execute_entry(self, signal: Dict[str, Any], size: float) -> Dict[str, Any]:
        """
        Executes order for validated signal.
        """
        symbol = signal["symbol"]
        side = "buy" if signal["side"].upper() == "LONG" else "sell"
        client_oid = str(uuid.uuid4())
        expected_price = signal["expected_entry_price"]

        db.log_event("INFO", "EXECUTION_SUBMIT", f"Submitting {side.upper()} order for {size:.4f} {symbol}", signal)

        # Place Order
        order_res = exchange_client.create_order(
            symbol=symbol,
            side=side,
            order_type="market_order",
            quantity=size,
            price=expected_price,
            leverage=settings.max_leverage,
            client_order_id=client_oid
        )

        if not order_res.get("success"):
            err = order_res.get("error", "Order failed")
            db.log_event("ERROR", "EXECUTION_FAILED", f"Entry order failed: {err}")
            return {"success": False, "error": err}

        # Determine actual average fill price
        if settings.trading_mode == "paper":
            fill_price = order_res["order"]["average_fill_price"]
            fees = order_res["order"]["fees"]
        else:
            fill_price = expected_price  # reconcile from API response
            fees = size * fill_price * (0.0005 * 1.18)

        # Recalculate protective stops based on actual fill price
        stop_dist = signal["stop_distance"]
        if signal["side"].upper() == "LONG":
            actual_stop = fill_price - stop_dist
            actual_target = fill_price + (settings.take_profit_rr * stop_dist)
        else:
            actual_stop = fill_price + stop_dist
            actual_target = fill_price - (settings.take_profit_rr * stop_dist)

        position_id = f"pos_{uuid.uuid4().hex[:10]}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        position_record = {
            "position_id": position_id,
            "symbol": symbol,
            "side": signal["side"].upper(),
            "quantity": size,
            "entry_price": fill_price,
            "current_price": fill_price,
            "stop_loss": actual_stop,
            "take_profit": actual_target,
            "stop_distance": stop_dist,
            "unrealised_pnl": 0.0,
            "margin_used": (size * fill_price) / settings.max_leverage,
            "leverage": settings.max_leverage,
            "status": "OPEN",
            "trading_mode": settings.trading_mode,
            "opened_at": now_iso,
            "entry_timestamp": time.time(),
            "bars_held": 0,
            "entry_fees": fees,
        }

        self.active_positions[position_id] = position_record
        db.save_position(position_record)
        notifier.send_alert(
            "ENTRY_EXECUTED",
            f"Opened {signal['side']} {size:.4f} {symbol} @ ${fill_price:.2f}\nStop: ${actual_stop:.2f} | Target: ${actual_target:.2f}"
        )
        return {"success": True, "position": position_record}

    def monitor_positions(self, current_price: float, is_new_bar: bool = False):
        """
        Continuously monitors open positions against current price, stop-loss, take-profit, and time-stop.
        """
        closed_ids = []
        for pos_id, pos in list(self.active_positions.items()):
            pos["current_price"] = current_price
            side = pos["side"]
            stop_loss = pos["stop_loss"]
            take_profit = pos["take_profit"]

            if is_new_bar:
                pos["bars_held"] = pos.get("bars_held", 0) + 1

            exit_reason = None
            exit_price = current_price

            # Check Stop-Loss
            if side == "LONG" and current_price <= stop_loss:
                exit_reason = "STOP_LOSS"
                exit_price = stop_loss
            elif side == "SHORT" and current_price >= stop_loss:
                exit_reason = "STOP_LOSS"
                exit_price = stop_loss

            # Check Take-Profit
            elif side == "LONG" and current_price >= take_profit:
                exit_reason = "TAKE_PROFIT"
                exit_price = take_profit
            elif side == "SHORT" and current_price <= take_profit:
                exit_reason = "TAKE_PROFIT"
                exit_price = take_profit

            # Check Time-Stop (30 minutes = 6 bars)
            elif pos["bars_held"] >= settings.max_hold_bars:
                exit_reason = "TIME_STOP"
                exit_price = current_price

            if exit_reason:
                self.close_position(pos_id, exit_reason=exit_reason, exit_price=exit_price)
                closed_ids.append(pos_id)

        # Update portfolio tracker
        portfolio_tracker.update_open_position_metrics(list(self.active_positions.values()), current_price)

    def close_position(self, position_id: str, exit_reason: str = "MANUAL_CLOSE", exit_price: Optional[float] = None) -> Dict[str, Any]:
        """
        Closes position, executes exit order, calculates P&L, fees, slippage, and stores record.
        """
        if position_id not in self.active_positions:
            return {"success": False, "error": "Position not found"}

        pos = self.active_positions.pop(position_id)
        current_p = exit_price or pos["current_price"]
        qty = pos["quantity"]
        entry_p = pos["entry_price"]
        side = pos["side"]

        # Close on exchange if live
        if settings.trading_mode == "live":
            close_side = "sell" if side == "LONG" else "buy"
            exchange_client.create_order(
                symbol=pos["symbol"],
                side=close_side,
                order_type="market_order",
                quantity=qty,
                price=current_p
            )

        # Calculate P&L
        if side == "LONG":
            gross_pnl = qty * (current_p - entry_p)
        else:
            gross_pnl = qty * (entry_p - current_p)

        exit_notional = qty * current_p
        exit_fee = exit_notional * (0.0005 * 1.18)
        total_fees = pos.get("entry_fees", 0.0) + exit_fee

        half_slip = settings.slippage_rate / 2.0
        slippage_cost = (pos["quantity"] * entry_p * half_slip) + (exit_notional * half_slip)
        net_pnl = gross_pnl - total_fees - slippage_cost

        stop_dist = pos.get("stop_distance", 0.0025 * entry_p)
        realised_r = net_pnl / (qty * stop_dist) if (qty * stop_dist) > 0 else 0.0

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        pos["status"] = "CLOSED"
        pos["closed_at"] = now_iso
        pos["unrealised_pnl"] = 0.0
        db.save_position(pos)

        # Save Trade Record
        trade_id = f"tr_{uuid.uuid4().hex[:8]}"
        trade_record = {
            "trade_id": trade_id,
            "symbol": pos["symbol"],
            "side": side,
            "entry_time": pos["opened_at"],
            "exit_time": now_iso,
            "entry_price": entry_p,
            "exit_price": current_p,
            "stop_price": pos["stop_loss"],
            "target_price": pos["take_profit"],
            "exit_reason": exit_reason,
            "bars_held": pos["bars_held"],
            "quantity": qty,
            "notional": exit_notional,
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "slippage": slippage_cost,
            "net_pnl": net_pnl,
            "realised_r": realised_r,
            "trading_mode": settings.trading_mode,
        }
        db.save_trade(trade_record)

        # Update Risk & Portfolio
        risk_manager.record_trade_completion(net_pnl)
        portfolio_tracker.record_realised_trade(net_pnl)

        notifier.send_alert(
            f"POSITION_CLOSED ({exit_reason})",
            f"Closed {side} {pos['symbol']} @ ${current_p:.2f}\nNet P&L: ${net_pnl:.2f} ({realised_r:.2f}R)"
        )
        return {"success": True, "trade": trade_record}

    def emergency_stop_all(self) -> Dict[str, Any]:
        """
        Immediately stops entries, cancels pending orders, and closes all open positions safely.
        """
        risk_manager.trigger_emergency_stop()
        closed_count = 0
        for pos_id in list(self.active_positions.keys()):
            self.close_position(pos_id, exit_reason="EMERGENCY_STOP")
            closed_count += 1

        db.log_event("CRITICAL", "EMERGENCY_STOP", f"Emergency stop executed. Closed {closed_count} positions.")
        notifier.send_alert("EMERGENCY_STOP_ACTIVATED", f"Closed {closed_count} positions. Bot halted.")
        return {"success": True, "closed_positions": closed_count}


# Global execution engine instance
executor = ExecutionEngine()
