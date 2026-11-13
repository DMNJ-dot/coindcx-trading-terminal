"""
CoinDCX Algorithmic Trading Terminal Launcher.
Starts the FastAPI application locally or on cloud PaaS ($PORT / 0.0.0.0).
Opens the default web browser automatically when running interactively on localhost.
"""
import os
import sys
import webbrowser
import threading
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import uvicorn
from backend.main import app
from backend.config.settings import settings


def open_browser(port: int):
    time.sleep(2.0)
    url = f"http://127.0.0.1:{port}"
    print(f"\n>> Opening Trading Dashboard in browser at: {url}\n", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.port))
    host = os.environ.get("HOST", settings.host)
    is_cloud = bool(os.environ.get("PORT") or os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT"))

    print("=" * 70, flush=True)
    print("   COINDCX INSTITUTIONAL CRYPTO TRADING TERMINAL v2.0", flush=True)
    print("   VWAP + EMA Trend Pullback Strategy Engine", flush=True)
    print("=" * 70, flush=True)
    print(f"Mode: {settings.trading_mode.upper()} | Host: {host}:{port}", flush=True)

    if not is_cloud:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
