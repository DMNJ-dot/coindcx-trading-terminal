"""
FastAPI WebSocket Connection Manager for Real-Time Terminal Streaming.
Broadcasts ticker updates, open position changes, trade executions, and logs.
"""
from typing import List, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
import json
import asyncio


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        dead_conns = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead_conns.append(connection)
        for dc in dead_conns:
            self.disconnect(dc)


ws_manager = ConnectionManager()
