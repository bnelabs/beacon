"""WebSocket endpoint for real-time job updates."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import Set
import asyncio
import json
import logging

from backend.database import get_db
from backend.api.job_events import job_payload

logger = logging.getLogger(__name__)

router = APIRouter()

# Store active WebSocket connections
active_connections: Set[WebSocket] = set()


class ConnectionManager:
    """Manages WebSocket connections and broadcasts"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept and store new WebSocket connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Send message to specific connection"""
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = set()
        message_json = json.dumps(message)

        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.error(f"Failed to broadcast to connection: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time job updates.

    Clients receive updates when jobs change status, progress updates,
    or when new jobs are created.
    """
    await manager.connect(websocket)

    try:
        # Send initial heartbeat
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to job updates stream"
        })

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (ping/pong for keepalive)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )

                # Handle ping
                if data == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send heartbeat if no message received
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def broadcast_job_update(job_data: dict):
    """Send one job update to every client attached to **this** process.

    Local fan-out only. Job progress is normally written by the Celery worker, a
    separate process, so callers should publish through
    ``backend.api.job_events.publish_job_update`` instead; the relay task started
    in ``backend/api/main.py`` subscribes to that bus and calls this.
    """
    message = {
        "type": "job_update",
        "job": job_data
    }
    await manager.broadcast(message)


# Export for use in other modules
__all__ = ['router', 'broadcast_job_update', 'job_payload', 'manager']
