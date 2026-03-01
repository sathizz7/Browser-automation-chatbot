"""
WebSocket Connection Manager.
Tracks active WebSocket connections and provides methods to send/broadcast messages.
"""

from fastapi import WebSocket
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """Accept a new WebSocket connection and register it."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"Client connected: {session_id} | Total: {len(self.active_connections)}")

    def disconnect(self, session_id: str):
        """Remove a WebSocket connection."""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"Client disconnected: {session_id} | Total: {len(self.active_connections)}")

    async def send_json(self, session_id: str, data: dict):
        """Send a JSON message to a specific connection."""
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(data)

    async def send_text(self, session_id: str, message: str):
        """Send a text message to a specific connection."""
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_text(message)

    async def broadcast(self, data: dict):
        """Broadcast a JSON message to all connected clients."""
        for session_id, ws in self.active_connections.items():
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.error(f"Error broadcasting to {session_id}: {e}")

    def get_connection(self, session_id: str) -> WebSocket | None:
        """Get a specific WebSocket connection by session ID."""
        return self.active_connections.get(session_id)

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)
