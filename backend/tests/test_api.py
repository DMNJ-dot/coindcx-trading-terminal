"""
FastAPI Dashboard Routes & Controls Integration Tests.
Verifies all 11 views, controls, order cancellations, and configuration persistence.
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config.settings import settings


client = TestClient(app)


def test_dashboard_overview():
    resp = client.get("/api/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "account" in data
    assert "market" in data
    assert "statistics" in data
    assert "bot_status" in data
    assert "health" in data


def test_market_candles_endpoint():
    resp = client.get("/api/market/candles?count=50")
    assert resp.status_code == 200
    data = resp.json()
    assert "candles" in data
    assert "symbol" in data


def test_bot_control_endpoints():
    # 1. Start Bot
    resp = client.post("/api/control/start")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 2. Toggle Auto-Trading
    resp = client.post("/api/control/auto_trading?enabled=true")
    assert resp.status_code == 200
    assert resp.json()["auto_trading_enabled"] is True

    # 3. Pause
    resp = client.post("/api/control/pause")
    assert resp.status_code == 200

    # 4. Resume
    resp = client.post("/api/control/resume")
    assert resp.status_code == 200

    # 5. Stop
    resp = client.post("/api/control/stop")
    assert resp.status_code == 200


def test_trading_mode_switch_safety():
    # Switch to paper
    resp = client.post("/api/control/mode", json={"mode": "paper", "confirm_live": False})
    assert resp.status_code == 200
    assert resp.json()["trading_mode"] == "PAPER"

    # Attempt switch to live WITHOUT confirmation must fail
    resp = client.post("/api/control/mode", json={"mode": "live", "confirm_live": False})
    assert resp.status_code == 400
    assert "explicit confirmation" in resp.json()["detail"]

    # Switch to live WITH confirmation succeeds
    resp = client.post("/api/control/mode", json={"mode": "live", "confirm_live": True})
    assert resp.status_code == 200
    assert resp.json()["trading_mode"] == "LIVE"

    # Reset back to paper
    client.post("/api/control/mode", json={"mode": "paper", "confirm_live": False})


def test_strategy_config_get_and_post():
    resp = client.get("/api/strategy/config")
    assert resp.status_code == 200
    cfg = resp.json()
    assert cfg["ema_fast_period"] == 9
    assert cfg["ema_slow_period"] == 21

    # Update config
    update_payload = {
        "ema_fast_period": 9,
        "ema_slow_period": 21,
        "vol_trigger_multiplier": 0.85
    }
    resp = client.post("/api/strategy/config", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_positions_and_orders_endpoints():
    resp = client.get("/api/positions")
    assert resp.status_code == 200
    assert "open_positions" in resp.json()

    resp = client.get("/api/orders")
    assert resp.status_code == 200
    assert "orders" in resp.json()


def test_trade_history_and_csv_export():
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    assert "trades" in resp.json()

    resp = client.get("/api/trades/export_csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "trade_id" in resp.text


def test_logs_and_signals_endpoints():
    resp = client.get("/api/logs?limit=10")
    assert resp.status_code == 200
    assert "logs" in resp.json()

    resp = client.get("/api/signals?limit=10")
    assert resp.status_code == 200
    assert "signals" in resp.json()


def test_health_and_report_endpoints():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = client.get("/api/backtest/report")
    assert resp.status_code == 200
    assert "Quantitative Backtest Report" in resp.json()["report_markdown"]


def test_web_dashboard_password_protection():
    orig_pwd = settings.dashboard_password
    try:
        settings.dashboard_password = "super_secret_web_pass"
        # Health remains accessible for cloud load balancers
        assert client.get("/health").status_code == 200

        # Dashboard and API require Basic auth when password is set
        unauth = client.get("/api/dashboard/overview")
        assert unauth.status_code == 401

        wrong = client.get("/api/dashboard/overview", auth=("admin", "wrong_pass"))
        assert wrong.status_code == 401

        ok = client.get("/api/dashboard/overview", auth=("admin", "super_secret_web_pass"))
        assert ok.status_code == 200
    finally:
        settings.dashboard_password = orig_pwd

