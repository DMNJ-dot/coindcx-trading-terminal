"""
Live Market Data Service & Multi-Coin Stream Manager.
Maintains candle buffers, calculates live indicators on closed bars,
and streams ticker updates for ALL COIN USDT PAIRS.
"""
import time
import threading
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
from backend.config.settings import settings, DATA_DIR
from backend.exchange.coindcx_client import exchange_client
from backend.backtest.indicators import add_all_indicators
from backend.database.db import db


class MarketDataManager:
    def __init__(self):
        self.symbol = settings.default_symbol
        self.timeframe = settings.timeframe
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # In-memory candles buffer
        self.candles_df: pd.DataFrame = pd.DataFrame()
        self.latest_ticker: Dict[str, Any] = {
            "symbol": self.symbol,
            "price": 0.0,
            "high_24h": 0.0,
            "low_24h": 0.0,
            "change_24h_pct": 0.0,
            "volume_24h": 0.0,
            "ema9": 0.0,
            "ema21": 0.0,
            "vwap": 0.0,
            "atr14": 0.0,
            "vol_ma20": 0.0,
            "trend": "NEUTRAL",
            "spread_est": settings.fixed_spread,
            "timestamp": time.time(),
        }
        self.supported_pairs: List[str] = [
            "B-BTC_USDT", "B-ETH_USDT", "B-SOL_USDT", "B-BNB_USDT", "B-DOGE_USDT", "B-XRP_USDT"
        ]

    def start(self):
        with self._lock:
            if not self.is_running:
                self.is_running = True
                self._load_initial_candles()
                self._thread = threading.Thread(target=self._update_loop, daemon=True)
                self._thread.start()
                db.log_event("INFO", "MARKET_DATA", f"Market data stream started for {self.symbol}")

    def stop(self):
        with self._lock:
            self.is_running = False
            db.log_event("INFO", "MARKET_DATA", "Market data stream stopped")

    def _load_initial_candles(self):
        """
        Pre-loads recent candles from CoinDCX public API or from local parquet cache.
        """
        raw_candles = exchange_client.get_market_candles(pair=self.symbol, interval="5m", limit=300)
        if raw_candles and len(raw_candles) > 30:
            df = pd.DataFrame(raw_candles)
            # Standardize columns
            col_map = {}
            for col in df.columns:
                c = col.lower()
                if "time" in c or "date" in c:
                    col_map[col] = "timestamp"
                elif "open" in c:
                    col_map[col] = "open"
                elif "high" in c:
                    col_map[col] = "high"
                elif "low" in c:
                    col_map[col] = "low"
                elif "close" in c:
                    col_map[col] = "close"
                elif "vol" in c:
                    col_map[col] = "volume"
            df = df.rename(columns=col_map)
            df["dt_utc"] = pd.to_datetime(df["timestamp"], unit="ms" if str(df["timestamp"].iloc[0]).isdigit() else None, utc=True)
            df = df.sort_values(by="dt_utc").reset_index(drop=True)
            self.candles_df = add_all_indicators(df)
        else:
            # Fallback to recent slice of local parquet
            parquet_path = str(DATA_DIR / "clean_5m.parquet")
            try:
                df = pd.read_parquet(parquet_path).tail(500).copy().reset_index(drop=True)
                self.candles_df = add_all_indicators(df)
            except Exception as e:
                db.log_event("WARNING", "MARKET_DATA", f"Could not load fallback parquet: {e}")

        self._refresh_ticker_from_candles()

    def _refresh_ticker_from_candles(self):
        if self.candles_df.empty:
            return
            
        last_row = self.candles_df.iloc[-1]
        price = float(last_row["close"])
        vwap = float(last_row.get("vwap", price))
        ema9 = float(last_row.get("ema9", price))
        ema21 = float(last_row.get("ema21", price))
        atr14 = float(last_row.get("atr14", 0.0))
        vol_ma = float(last_row.get("vol_ma20", 0.0))
        
        # 24h stats (last 288 bars = 24h)
        slice_24h = self.candles_df.tail(288)
        high_24h = float(slice_24h["high"].max())
        low_24h = float(slice_24h["low"].min())
        open_24h = float(slice_24h["open"].iloc[0])
        change_pct = ((price - open_24h) / open_24h) * 100.0 if open_24h > 0 else 0.0
        vol_24h = float(slice_24h["volume"].sum())

        trend = "BULLISH" if (price > vwap and ema9 > ema21) else ("BEARISH" if (price < vwap and ema9 < ema21) else "NEUTRAL")

        self.latest_ticker = {
            "symbol": self.symbol,
            "price": price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "change_24h_pct": round(change_pct, 2),
            "volume_24h": round(vol_24h, 2),
            "ema9": round(ema9, 2),
            "ema21": round(ema21, 2),
            "vwap": round(vwap, 2),
            "atr14": round(atr14, 2),
            "vol_ma20": round(vol_ma, 2),
            "trend": trend,
            "spread_est": settings.fixed_spread,
            "timestamp": time.time(),
        }

    def _update_loop(self):
        while self.is_running:
            try:
                # Poll candles periodically
                candles = exchange_client.get_market_candles(pair=self.symbol, interval="5m", limit=50)
                if candles:
                    df = pd.DataFrame(candles)
                    col_map = {}
                    for col in df.columns:
                        c = col.lower()
                        if "time" in c or "date" in c:
                            col_map[col] = "timestamp"
                        elif "open" in c:
                            col_map[col] = "open"
                        elif "high" in c:
                            col_map[col] = "high"
                        elif "low" in c:
                            col_map[col] = "low"
                        elif "close" in c:
                            col_map[col] = "close"
                        elif "vol" in c:
                            col_map[col] = "volume"
                    df = df.rename(columns=col_map)
                    df["dt_utc"] = pd.to_datetime(df["timestamp"], unit="ms" if str(df["timestamp"].iloc[0]).isdigit() else None, utc=True)
                    
                    with self._lock:
                        # Append and recompute indicators
                        combined = pd.concat([self.candles_df, df]).drop_duplicates(subset=["dt_utc"]).sort_values(by="dt_utc").reset_index(drop=True)
                        self.candles_df = add_all_indicators(combined.tail(500))
                        self._refresh_ticker_from_candles()
            except Exception as e:
                db.log_event("WARNING", "MARKET_UPDATE_LOOP", f"Update error: {e}")
                
            time.sleep(5)  # Poll every 5s for fresh candle telemetry

    def get_latest_candles(self, count: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            if self.candles_df.empty:
                return []
            sub = self.candles_df.tail(count).copy()
            records = []
            for _, r in sub.iterrows():
                records.append({
                    "time": int(pd.to_datetime(r["dt_utc"]).timestamp()),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                    "vwap": float(r["vwap"]) if "vwap" in r and not np.isnan(r["vwap"]) else None,
                    "ema9": float(r["ema9"]) if "ema9" in r and not np.isnan(r["ema9"]) else None,
                    "ema21": float(r["ema21"]) if "ema21" in r and not np.isnan(r["ema21"]) else None,
                })
            return records

    def get_latest_ticker(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.latest_ticker)


# Global market data manager instance
market_data_manager = MarketDataManager()
