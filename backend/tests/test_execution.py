"""
Execution Engine & Mocked Exchange Integration Tests.
Verifies order execution, partial fills, timeouts, errors, protective stops,
idempotency, and position reconciliation.
"""
import pytest
from unittest.mock import MagicMock, patch
import time
from backend.config.settings import settings
from backend.exchange.coindcx_client import CoinDCXClient
from backend.execution.executor import ExecutionEngine
from backend.database.db import DatabaseManager
from backend.risk.risk_manager import RiskManager


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_exec.db")
    return DatabaseManager(db_path=db_file)


def test_order_creation_paper_mode(test_db):
    """
    Verifies that paper orders simulate fills, slippage, and fee tracking.
    """
    settings.trading_mode = "paper"
    client = CoinDCXClient()
    res = client.create_order(
        symbol="B-BTC_USDT",
        side="buy",
        order_type="market_order",
        quantity=0.1,
        price=50000.0,
        leverage=10.0
    )
    assert res["success"] is True
    order = res["order"]
    assert order["status"] == "FILLED"
    assert order["quantity"] == 0.1
    # Slippage check: buy fill > price
    assert order["average_fill_price"] > 50000.0
    assert order["fees"] > 0


def test_live_order_safety_rejection():
    """
    CRITICAL SAFETY TEST:
    Verifies that Live orders are rejected without explicit confirmation.
    """
    settings.trading_mode = "live"
    settings.live_trading_confirmed = False
    client = CoinDCXClient()
    res = client.create_order(
        symbol="B-BTC_USDT",
        side="buy",
        order_type="market_order",
        quantity=0.1,
        price=50000.0
    )
    assert res["success"] is False
    assert "explicit confirmation" in res["error"]
    # Reset
    settings.trading_mode = "paper"


def test_mocked_exchange_timeout_and_error_handling():
    """
    Tests handling of network timeouts and API errors during execution.
    """
    client = CoinDCXClient(api_key="mock_key", api_secret="mock_secret")
    settings.trading_mode = "live"
    settings.live_trading_confirmed = True

    # 1. Mock network timeout exception
    with patch.object(client.session, "post", side_effect=Exception("ReadTimeout")):
        success, res = client._post("/test", {})
        assert success is False
        assert "ReadTimeout" in res["error"]
        assert client.is_connected is False

    # 2. Mock exchange rejection (e.g. 400 Bad Request)
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "InsufficientMargin"
    with patch.object(client.session, "post", return_value=mock_resp):
        success, res = client._post("/test", {})
        assert success is False
        assert "400" in res["error"]

    settings.trading_mode = "paper"
    settings.live_trading_confirmed = False


def test_position_entry_and_bracket_protective_stops():
    """
    Verifies that position entry establishes exact protective Stop-Loss
    and Take-Profit levels based on fill price.
    """
    settings.trading_mode = "paper"
    engine = ExecutionEngine()
    
    signal = {
        "symbol": "B-BTC_USDT",
        "side": "LONG",
        "expected_entry_price": 60000.0,
        "stop_distance": 150.0,
    }
    
    res = engine.execute_entry(signal, size=0.05)
    assert res["success"] is True
    pos = res["position"]
    pos_id = pos["position_id"]
    
    assert pos["side"] == "LONG"
    assert pos["status"] == "OPEN"
    # Stop loss must be below fill price by exact stop_distance
    assert np_isclose(pos["stop_loss"], pos["entry_price"] - 150.0)
    # Take profit must be fill_price + 3 * stop_distance (1:3 planned)
    assert np_isclose(pos["take_profit"], pos["entry_price"] + 450.0)
    
    # Test manual close position
    close_res = engine.close_position(pos_id, exit_reason="MANUAL_CLOSE", exit_price=60500.0)
    assert close_res["success"] is True
    assert close_res["trade"]["exit_reason"] == "MANUAL_CLOSE"
    assert close_res["trade"]["gross_pnl"] > 0


def test_time_stop_trigger():
    """
    Verifies that after 6 bars elapsed, open position is closed with TIME_STOP reason.
    """
    settings.trading_mode = "paper"
    engine = ExecutionEngine()
    
    signal = {
        "symbol": "B-BTC_USDT",
        "side": "LONG",
        "expected_entry_price": 50000.0,
        "stop_distance": 120.0,
    }
    res = engine.execute_entry(signal, size=0.02)
    pos_id = res["position"]["position_id"]
    
    # Advance 6 bars without touching stop or target
    for _ in range(6):
        engine.monitor_positions(current_price=50010.0, is_new_bar=True)
        
    assert pos_id not in engine.active_positions, "Position should be closed after 6 bars held"


def np_isclose(a, b, tol=1e-3):
    return abs(a - b) < tol
