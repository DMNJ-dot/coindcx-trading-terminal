"""
CoinDCX Algorithmic Trading Terminal Main Application Entrypoint.
FastAPI Backend + WebSocket Live Data Streamer + Static Dashboard Server.
Supports local execution and cloud web hosting (0.0.0.0:$PORT) with optional HTTP Basic Auth.
"""
import os
import base64
import secrets
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.config.settings import settings, BASE_DIR, RESULTS_DIR
from backend.api.routes import api_router
from backend.api.websocket_handler import ws_manager
from backend.market_data.stream_manager import market_data_manager
from backend.strategies.strategy_engine import strategy_engine
from backend.monitoring.health_monitor import health_monitor
from backend.database.db import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    db.log_event("INFO", "LIFECYCLE", "CoinDCX Trading Terminal initializing...")
    market_data_manager.start()
    health_monitor.start()
    strategy_engine.start()
    
    # Background periodic websocket broadcast
    broadcast_task = asyncio.create_task(periodic_ws_broadcast())
    yield
    # Shutdown sequence
    broadcast_task.cancel()
    strategy_engine.stop()
    health_monitor.stop()
    market_data_manager.stop()
    db.log_event("INFO", "LIFECYCLE", "CoinDCX Trading Terminal shut down cleanly.")


app = FastAPI(
    title="CoinDCX Automated Trading Terminal",
    version="2.0.0",
    lifespan=lifespan
)

# Optional Web Authentication Middleware (active when DASHBOARD_PASSWORD is set)
@app.middleware("http")
async def web_auth_middleware(request: Request, call_next):
    # Allow public healthchecks for cloud PaaS load balancers
    if request.url.path == "/health":
        return await call_next(request)

    if settings.dashboard_password:
        auth_header = request.headers.get("Authorization")
        authorized = False
        if auth_header and auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
                user, pwd = decoded.split(":", 1)
                user_ok = secrets.compare_digest(user, settings.dashboard_username)
                pwd_ok = secrets.compare_digest(pwd, settings.dashboard_password)
                authorized = user_ok and pwd_ok
            except Exception:
                authorized = False
        if not authorized:
            return Response(
                content="Authentication required to access CoinDCX Trading Terminal.",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="CoinDCX Trading Terminal"'},
            )
    return await call_next(request)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST routes
app.include_router(api_router)


@app.get("/health")
def health_check():
    """Public cloud healthcheck endpoint."""
    return JSONResponse({
        "status": "ok",
        "mode": settings.trading_mode.upper(),
        "bot_running": strategy_engine.is_running,
    })


# WebSocket streaming endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection open and receive any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


async def periodic_ws_broadcast():
    """
    Broadcasts real-time telemetry updates to all connected dashboard clients every second.
    """
    while True:
        try:
            ticker = market_data_manager.get_latest_ticker()
            bot_status = strategy_engine.get_status()
            overview = {
                "type": "TELEMETRY_UPDATE",
                "ticker": ticker,
                "bot_status": bot_status,
                "time": ticker["timestamp"]
            }
            await ws_manager.broadcast(overview)
        except Exception:
            pass
        await asyncio.sleep(1)


# Static Dashboard Serving
frontend_dir = str(BASE_DIR / "frontend")
results_dir = str(RESULTS_DIR)

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

if os.path.exists(results_dir):
    app.mount("/results", StaticFiles(directory=results_dir), name="results")


@app.get("/")
def serve_dashboard():
    index_file = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "CoinDCX Algorithmic Trading Terminal Backend Running"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", settings.port))
    uvicorn.run("backend.main:app", host=settings.host, port=port, reload=False)
