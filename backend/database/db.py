"""
Database Management & Persistence Engine (SQLite).
Retains trading history, orders, positions, signals, logs, and configuration across restarts.
"""
import sqlite3
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import threading
from backend.config.settings import settings


class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.db_path
        self._lock = threading.Lock()
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. System Config / Settings table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)

            # 2. Orders table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                client_order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL,
                quantity REAL NOT NULL,
                filled_quantity REAL DEFAULT 0,
                average_fill_price REAL DEFAULT 0,
                status TEXT NOT NULL,
                fees REAL DEFAULT 0,
                trading_mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)

            # 3. Positions table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                unrealised_pnl REAL DEFAULT 0,
                margin_used REAL DEFAULT 0,
                leverage REAL DEFAULT 10,
                status TEXT NOT NULL, -- 'OPEN', 'CLOSED'
                trading_mode TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT
            )
            """)

            # 4. Trades History table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                bars_held INTEGER NOT NULL,
                quantity REAL NOT NULL,
                notional REAL NOT NULL,
                gross_pnl REAL NOT NULL,
                fees REAL NOT NULL,
                slippage REAL NOT NULL,
                net_pnl REAL NOT NULL,
                realised_r REAL NOT NULL,
                trading_mode TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)

            # 5. Signals table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                trigger_close REAL NOT NULL,
                expected_entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                status TEXT NOT NULL, -- 'GENERATED', 'EXECUTED', 'REJECTED'
                rejection_reason TEXT,
                created_at TEXT NOT NULL
            )
            """)

            # 6. System Logs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT
            )
            """)

            # 7. Equity History table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS equity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL,
                unrealised_pnl REAL DEFAULT 0,
                realised_pnl REAL DEFAULT 0,
                trading_mode TEXT NOT NULL
            )
            """)

            conn.commit()

    # Log recording
    def log_event(self, level: str, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            ts = datetime.utcnow().isoformat() + "Z"
            details_str = json.dumps(details) if details else None
            cursor.execute(
                "INSERT INTO system_logs (timestamp, level, category, message, details) VALUES (?, ?, ?, ?, ?)",
                (ts, level, category, message, details_str)
            )
            conn.commit()

    def get_recent_logs(self, limit: int = 100, level: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM system_logs"
            params = []
            if level:
                query += " WHERE level = ?"
                params.append(level)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # Signal persistence
    def save_signal(self, sig: Dict[str, Any]):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat() + "Z"
            cursor.execute("""
            INSERT OR REPLACE INTO signals 
            (signal_id, timestamp, symbol, side, trigger_close, expected_entry_price, stop_price, target_price, status, rejection_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sig["signal_id"], sig["timestamp"], sig["symbol"], sig["side"],
                sig["trigger_close"], sig["expected_entry_price"], sig["stop_price"],
                sig["target_price"], sig["status"], sig.get("rejection_reason"), now
            ))
            conn.commit()

    def get_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # Trade persistence
    def save_trade(self, t: Dict[str, Any]):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat() + "Z"
            cursor.execute("""
            INSERT OR REPLACE INTO trades
            (trade_id, symbol, side, entry_time, exit_time, entry_price, exit_price, stop_price, target_price,
             exit_reason, bars_held, quantity, notional, gross_pnl, fees, slippage, net_pnl, realised_r, trading_mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t["trade_id"], t["symbol"], t["side"], t["entry_time"], t["exit_time"],
                t["entry_price"], t["exit_price"], t["stop_price"], t["target_price"],
                t["exit_reason"], t["bars_held"], t["quantity"], t["notional"],
                t["gross_pnl"], t["fees"], t["slippage"], t["net_pnl"], t["realised_r"],
                t["trading_mode"], now
            ))
            conn.commit()

    def get_trades(self, limit: int = 200, trading_mode: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM trades"
            params = []
            if trading_mode:
                query += " WHERE trading_mode = ?"
                params.append(trading_mode)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # Position persistence
    def save_position(self, pos: Dict[str, Any]):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO positions
            (position_id, symbol, side, quantity, entry_price, current_price, stop_loss, take_profit,
             unrealised_pnl, margin_used, leverage, status, trading_mode, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pos["position_id"], pos["symbol"], pos["side"], pos["quantity"],
                pos["entry_price"], pos["current_price"], pos.get("stop_loss"), pos.get("take_profit"),
                pos.get("unrealised_pnl", 0.0), pos.get("margin_used", 0.0), pos.get("leverage", 10.0),
                pos["status"], pos["trading_mode"], pos["opened_at"], pos.get("closed_at")
            ))
            conn.commit()

    def get_open_positions(self, trading_mode: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM positions WHERE status = 'OPEN'"
            params = []
            if trading_mode:
                query += " AND trading_mode = ?"
                params.append(trading_mode)
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # Order persistence
    def save_order(self, order: Dict[str, Any]):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat() + "Z"
            cursor.execute("""
            INSERT OR REPLACE INTO orders
            (order_id, client_order_id, symbol, side, order_type, price, quantity, filled_quantity,
             average_fill_price, status, fees, trading_mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order["order_id"], order.get("client_order_id"), order["symbol"], order["side"],
                order["order_type"], order.get("price"), order["quantity"], order.get("filled_quantity", 0.0),
                order.get("average_fill_price", 0.0), order["status"], order.get("fees", 0.0),
                order["trading_mode"], order.get("created_at", now), now
            ))
            conn.commit()

    def get_orders(self, limit: int = 100, trading_mode: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM orders"
            params = []
            if trading_mode:
                query += " WHERE trading_mode = ?"
                params.append(trading_mode)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # Equity tracking
    def record_equity_snapshot(self, equity: float, unrealised_pnl: float, realised_pnl: float, trading_mode: str):
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            ts = datetime.utcnow().isoformat() + "Z"
            cursor.execute(
                "INSERT INTO equity_history (timestamp, equity, unrealised_pnl, realised_pnl, trading_mode) VALUES (?, ?, ?, ?, ?)",
                (ts, equity, unrealised_pnl, realised_pnl, trading_mode)
            )
            conn.commit()

    def get_equity_history(self, limit: int = 500, trading_mode: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM equity_history"
            params = []
            if trading_mode:
                query += " WHERE trading_mode = ?"
                params.append(trading_mode)
            query += " ORDER BY id ASC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]


# Global database manager instance
db = DatabaseManager()
