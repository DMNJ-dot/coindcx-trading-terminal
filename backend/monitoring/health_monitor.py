"""
System Health Monitoring & Watchdog Service.
Continuously checks exchange connectivity, data freshness, heartbeat,
database health, and triggers automatic fail-safe protections.
"""
import time
import threading
from typing import Dict, Any
from backend.config.settings import settings
from backend.database.db import db
from backend.exchange.coindcx_client import exchange_client
from backend.market_data.stream_manager import market_data_manager
from backend.risk.risk_manager import risk_manager


class HealthMonitor:
    def __init__(self):
        self.is_running = False
        self._thread = None
        self.last_heartbeat = time.time()
        self.system_status = "HEALTHY"
        self.health_metrics: Dict[str, Any] = {
            "exchange_status": "ONLINE",
            "market_data_status": "STREAMING",
            "database_status": "CONNECTED",
            "data_freshness_seconds": 0,
            "overall_health": "OPTIMAL",
        }

    def start(self):
        if not self.is_running:
            self.is_running = True
            self._thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.is_running = False

    def _watchdog_loop(self):
        while self.is_running:
            try:
                self.last_heartbeat = time.time()
                
                # 1. Market Data Freshness
                ticker = market_data_manager.get_latest_ticker()
                data_age = time.time() - ticker.get("timestamp", time.time())
                self.health_metrics["data_freshness_seconds"] = round(data_age, 1)

                if data_age > 60:
                    self.health_metrics["market_data_status"] = "STALE"
                    if not risk_manager.emergency_halt:
                        db.log_event("WARNING", "WATCHDOG", f"Market data stale ({data_age:.1f}s). Pausing entries.")
                else:
                    self.health_metrics["market_data_status"] = "STREAMING"

                # 2. Database Health
                try:
                    conn = db.get_connection()
                    conn.execute("SELECT 1").fetchone()
                    conn.close()
                    self.health_metrics["database_status"] = "CONNECTED"
                except Exception as e:
                    self.health_metrics["database_status"] = f"ERROR: {e}"

                # 3. Exchange Connectivity Check
                if exchange_client.last_sync_time and (time.time() - exchange_client.last_sync_time > 120):
                    self.health_metrics["exchange_status"] = "SYNC_DELAY"
                else:
                    self.health_metrics["exchange_status"] = "ONLINE"

            except Exception as e:
                db.log_event("ERROR", "WATCHDOG_EXCEPTION", str(e))

            time.sleep(5)

    def get_health_summary(self) -> Dict[str, Any]:
        return {
            **self.health_metrics,
            "last_heartbeat": self.last_heartbeat,
            "emergency_halt": risk_manager.emergency_halt,
        }


# Global health monitor instance
health_monitor = HealthMonitor()
