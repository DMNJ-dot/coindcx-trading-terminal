"""
CoinDCX Futures API Integration Client.
Handles official REST endpoints, HMAC-SHA256 request signing, order execution,
protective orders, error reconciliation, and paper trading simulation.
"""
import time
import hmac
import hashlib
import json
import uuid
from typing import Dict, Any, List, Optional, Tuple
import requests
from backend.config.settings import settings
from backend.database.db import db


class CoinDCXClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        public_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.coindcx_api_key
        self.api_secret = api_secret or settings.coindcx_api_secret
        self.base_url = base_url or settings.coindcx_base_url
        self.public_url = public_url or settings.coindcx_public_url
        self.session = requests.Session()
        self.is_connected = False
        self.last_sync_time = None
        self.last_error = None

    def _generate_signature(self, json_body: str) -> str:
        """
        Generates HMAC-SHA256 signature in hexadecimal format
        signed with the API secret.
        """
        if not self.api_secret:
            return ""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            json_body.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        """
        Sends an authenticated POST request to CoinDCX Derivatives endpoint.
        """
        url = f"{self.base_url}{endpoint}"
        payload["timestamp"] = int(round(time.time() * 1000))
        json_body = json.dumps(payload, separators=(",", ":"))
        signature = self._generate_signature(json_body)

        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-SIGNATURE": signature,
        }

        try:
            resp = self.session.post(url, data=json_body, headers=headers, timeout=10)
            if resp.status_code == 200:
                self.is_connected = True
                self.last_sync_time = time.time()
                return True, resp.json()
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text}"
                self.last_error = err_msg
                db.log_event("ERROR", "EXCHANGE_REST", err_msg, {"endpoint": endpoint})
                return False, {"error": err_msg}
        except Exception as e:
            err_msg = f"Request exception: {str(e)}"
            self.last_error = err_msg
            self.is_connected = False
            db.log_event("ERROR", "EXCHANGE_CONNECTION", err_msg, {"endpoint": endpoint})
            return False, {"error": err_msg}

    def _get_public(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        """
        Sends a public unauthenticated request.
        """
        url = f"{self.public_url}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return True, resp.json()
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text}"
                return False, {"error": err_msg}
        except Exception as e:
            return False, {"error": str(e)}

    # 1. Market Data: Public Candles
    def get_market_candles(self, pair: str = "B-BTC_USDT", interval: str = "5m", limit: int = 200) -> List[Dict[str, Any]]:
        """
        Retrieves real candlestick history from public CoinDCX endpoints.
        """
        success, data = self._get_public("/market_data/candles/", params={"pair": pair, "interval": interval, "limit": limit})
        if success and isinstance(data, list):
            return data
        return []

    # 2. Instruments
    def get_active_instruments(self) -> List[Dict[str, Any]]:
        """
        Retrieves active futures perpetual contracts available on CoinDCX.
        """
        url = f"{self.base_url}/exchange/v1/derivatives/futures/data/active_instruments"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                self.is_connected = True
                return resp.json()
        except Exception as e:
            self.last_error = str(e)
        return []

    # 3. Account Wallets / Balance
    def get_futures_wallets(self) -> List[Dict[str, Any]]:
        """
        Fetches user futures margin and wallet balance.
        """
        if settings.trading_mode == "paper":
            # In paper trading, retrieve state from database / settings
            return [{
                "currency_short_name": "USDT",
                "balance": settings.starting_equity,
                "locked_balance": 0.0,
                "cross_order_margin": 0.0,
            }]
            
        success, data = self._post("/exchange/v1/derivatives/futures/wallets", {})
        if success and isinstance(data, list):
            return data
        return []

    # 4. Open Positions
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Fetches live open positions from the exchange.
        """
        if settings.trading_mode == "paper":
            return db.get_open_positions(trading_mode="paper")
            
        success, data = self._post("/exchange/v1/derivatives/futures/positions", {"page": "1", "size": "20"})
        if success and isinstance(data, list):
            return data
        return []

    # 5. List Orders
    def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches open or filled orders.
        """
        if settings.trading_mode == "paper":
            return db.get_orders(trading_mode="paper")

        payload = {"page": "1", "size": "50"}
        if status:
            payload["status"] = status
        success, data = self._post("/exchange/v1/derivatives/futures/orders", payload)
        if success and isinstance(data, list):
            return data
        return []

    # 6. Create Futures Order
    def create_order(
        self,
        symbol: str,
        side: str,  # 'buy' or 'sell'
        order_type: str,  # 'market_order' or 'limit_order'
        quantity: float,
        price: Optional[float] = None,
        leverage: float = 10.0,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submits a new futures order to CoinDCX or simulates fill in paper mode.
        """
        cid = client_order_id or str(uuid.uuid4())
        
        # PAPER TRADING SIMULATION
        if settings.trading_mode == "paper":
            order_id = f"paper_ord_{uuid.uuid4().hex[:10]}"
            fill_price = price if price is not None else 0.0
            
            # Apply simulated slippage
            half_slip = settings.slippage_rate / 2.0
            if side.lower() == "buy":
                sim_fill_price = fill_price * (1.0 + half_slip)
            else:
                sim_fill_price = fill_price * (1.0 - half_slip)
                
            notional = quantity * sim_fill_price
            sim_fee = notional * (0.0005 * 1.18)  # 0.059%
            
            order_record = {
                "order_id": order_id,
                "client_order_id": cid,
                "symbol": symbol,
                "side": side.lower(),
                "order_type": order_type,
                "price": fill_price,
                "quantity": quantity,
                "filled_quantity": quantity,
                "average_fill_price": sim_fill_price,
                "status": "FILLED",
                "fees": sim_fee,
                "trading_mode": "paper",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            db.save_order(order_record)
            db.log_event("INFO", "PAPER_ORDER", f"Simulated {side} fill for {quantity:.4f} {symbol} @ {sim_fill_price:.2f}", order_record)
            return {"success": True, "order": order_record}

        # LIVE EXECUTION SAFETY CHECKS
        if settings.trading_mode == "live":
            if not settings.live_trading_confirmed:
                err = "Live trading order rejected: Live trading mode has not received explicit confirmation!"
                db.log_event("CRITICAL", "SAFETY_CHECK", err)
                return {"success": False, "error": err}
                
            if not self.api_key or not self.api_secret:
                err = "Live order rejected: CoinDCX API credentials missing!"
                db.log_event("CRITICAL", "AUTH", err)
                return {"success": False, "error": err}

        # Format official CoinDCX payload
        order_payload = {
            "side": side.lower(),
            "pair": symbol,
            "order_type": order_type,
            "total_quantity": quantity,
            "leverage": int(leverage),
            "notification": "no_notification",
        }
        if order_type == "limit_order" and price is not None:
            order_payload["price"] = str(price)
            order_payload["time_in_force"] = "good_till_cancel"

        body = {
            "client_order_id": cid,
            "order": order_payload
        }

        success, res = self._post("/exchange/v1/derivatives/futures/orders/create", body)
        if success:
            db.log_event("INFO", "LIVE_ORDER", f"Order submitted to CoinDCX: {cid}", res)
            return {"success": True, "data": res}
        else:
            db.log_event("ERROR", "LIVE_ORDER_FAILED", f"Order failed: {cid}", res)
            return {"success": False, "error": res.get("error", "Unknown error")}

    # 7. Cancel Order
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancels an open order by ID.
        """
        if settings.trading_mode == "paper":
            return {"success": True, "message": f"Paper order {order_id} cancelled"}
            
        success, res = self._post("/exchange/v1/derivatives/futures/orders/cancel", {"id": order_id})
        return {"success": success, "data": res}


# Global exchange client instance
exchange_client = CoinDCXClient()
