"""
WebSocket routes for real-time updates in BEACON Platform

Provides real-time job status updates, system notifications, and live data streams.
"""

import asyncio
import json
from typing import Dict, Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job
from services.error_logger import ErrorLogger


router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        # Map of job_id to set of websocket connections
        self.job_connections: Dict[int, Set[WebSocket]] = {}
        # All active connections
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        self.active_connections.discard(websocket)

        # Remove from job-specific connections
        for job_id, connections in list(self.job_connections.items()):
            if websocket in connections:
                connections.discard(websocket)
                if not connections:
                    del self.job_connections[job_id]

    def subscribe_to_job(self, websocket: WebSocket, job_id: int):
        """Subscribe a connection to job updates."""
        if job_id not in self.job_connections:
            self.job_connections[job_id] = set()
        self.job_connections[job_id].add(websocket)

    def unsubscribe_from_job(self, websocket: WebSocket, job_id: int):
        """Unsubscribe a connection from job updates."""
        if job_id in self.job_connections:
            self.job_connections[job_id].discard(websocket)
            if not self.job_connections[job_id]:
                del self.job_connections[job_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific connection."""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    async def broadcast_job_update(self, job_id: int, message: dict, db: Session):
        """Broadcast job update to all subscribers."""
        if job_id not in self.job_connections:
            return

        # Add timestamp
        message["timestamp"] = datetime.utcnow().isoformat()

        # Send to all subscribers
        disconnected = set()
        for websocket in self.job_connections[job_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.add(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            self.disconnect(websocket)

    async def broadcast_to_all(self, message: dict):
        """Broadcast message to all connections."""
        message["timestamp"] = datetime.utcnow().isoformat()

        disconnected = set()
        for websocket in self.active_connections:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.add(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            self.disconnect(websocket)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for general system updates.

    Connect to this endpoint to receive real-time system notifications.
    """
    await manager.connect(websocket)

    try:
        # Send welcome message
        await manager.send_personal_message({
            "type": "connected",
            "message": "Connected to BEACON real-time updates",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)

        # Keep connection alive and handle incoming messages
        while True:
            # Receive messages from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

                elif message_type == "subscribe_jobs":
                    # Client wants updates on all jobs
                    await manager.send_personal_message({
                        "type": "subscribed",
                        "topic": "jobs",
                        "message": "Subscribed to job updates"
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "error",
                    "message": "Invalid JSON message"
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws/jobs/{job_id}")
async def job_websocket_endpoint(
    websocket: WebSocket,
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time job status updates.

    Connect to this endpoint to receive updates for a specific job.

    **Usage:**
    ```javascript
    const ws = new WebSocket(`ws://localhost:3456/api/ws/jobs/${jobId}`)

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      console.log('Job update:', data)
    }
    ```

    **Message Types:**
    - `status_change`: Job status changed (pending → running → completed/failed)
    - `progress`: Job progress update (0-100%)
    - `log`: Job log message
    - `result`: Job completed with results
    - `error`: Job error occurred
    """
    await manager.connect(websocket)
    manager.subscribe_to_job(websocket, job_id)

    try:
        # Verify job exists
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            await manager.send_personal_message({
                "type": "error",
                "message": f"Job {job_id} not found"
            }, websocket)
            return

        # Send initial job status
        await manager.send_personal_message({
            "type": "connected",
            "job_id": job_id,
            "status": job.status,
            "progress": job.progress or 0,
            "message": f"Subscribed to job {job_id} updates",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)

        # Start monitoring job status
        asyncio.create_task(monitor_job_status(job_id, db))

        # Keep connection alive
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "job_id": job_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

                elif message_type == "get_status":
                    # Send current job status
                    db.refresh(job)
                    await manager.send_personal_message({
                        "type": "status",
                        "job_id": job_id,
                        "status": job.status,
                        "progress": job.progress or 0,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "error",
                    "message": "Invalid JSON message"
                }, websocket)

    except WebSocketDisconnect:
        manager.unsubscribe_from_job(websocket, job_id)
        manager.disconnect(websocket)


async def monitor_job_status(job_id: int, db: Session):
    """
    Monitor job status and broadcast updates.

    This runs in the background and polls the database for changes.
    """
    from database import SessionLocal

    last_status = None
    last_progress = None

    while True:
        try:
            # Use new session for background task
            bg_db = SessionLocal()
            try:
                job = bg_db.query(Job).filter(Job.id == job_id).first()

                if not job:
                    break

                # Check if status changed
                if job.status != last_status:
                    await manager.broadcast_job_update(job_id, {
                        "type": "status_change",
                        "job_id": job_id,
                        "status": job.status,
                        "previous_status": last_status,
                        "progress": job.progress or 0,
                    }, bg_db)
                    last_status = job.status

                # Check if progress changed
                current_progress = job.progress or 0
                if current_progress != last_progress:
                    await manager.broadcast_job_update(job_id, {
                        "type": "progress",
                        "job_id": job_id,
                        "progress": current_progress,
                        "status": job.status,
                    }, bg_db)
                    last_progress = current_progress

                # If job is completed or failed, send final update and stop monitoring
                if job.status in ["completed", "failed", "cancelled"]:
                    await manager.broadcast_job_update(job_id, {
                        "type": "final",
                        "job_id": job_id,
                        "status": job.status,
                        "progress": 100 if job.status == "completed" else current_progress,
                        "result": job.result,
                        "error": job.error,
                    }, bg_db)
                    break

            finally:
                bg_db.close()

            # Poll every 2 seconds
            await asyncio.sleep(2)

        except Exception as e:
            # Log error but continue monitoring
            print(f"Error monitoring job {job_id}: {e}")
            await asyncio.sleep(5)


# Helper function to broadcast job updates from Celery tasks
def broadcast_job_update_sync(job_id: int, message: dict):
    """
    Synchronous wrapper to broadcast job updates from Celery tasks.

    Usage in Celery tasks:
    ```python
    from api.routes.websocket import broadcast_job_update_sync

    broadcast_job_update_sync(job_id, {
        "type": "progress",
        "progress": 50,
        "message": "Halfway through data collection"
    })
    ```
    """
    # This would need to be implemented with a message queue or Redis pub/sub
    # For now, updates will be detected by the polling mechanism
    pass


@router.get("/ws/test")
async def websocket_test_page():
    """
    Test page for WebSocket connections.

    Returns HTML page with WebSocket test client.
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BEACON WebSocket Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            #messages { border: 1px solid #ccc; height: 400px; overflow-y: scroll; padding: 10px; margin: 10px 0; }
            .message { margin: 5px 0; padding: 5px; }
            .status_change { background: #e3f2fd; }
            .progress { background: #f3e5f5; }
            .error { background: #ffebee; }
            .connected { background: #e8f5e9; }
            button { margin: 5px; padding: 10px; }
            input { padding: 5px; margin: 5px; }
        </style>
    </head>
    <body>
        <h1>BEACON WebSocket Test Client</h1>

        <div>
            <label>Job ID: <input type="number" id="jobId" value="1"></label>
            <button onclick="connectToJob()">Connect to Job</button>
            <button onclick="disconnect()">Disconnect</button>
            <button onclick="sendPing()">Send Ping</button>
            <button onclick="getStatus()">Get Status</button>
            <button onclick="clearMessages()">Clear</button>
        </div>

        <div id="status">Not connected</div>
        <div id="messages"></div>

        <script>
            let ws = null;

            function connectToJob() {
                const jobId = document.getElementById('jobId').value;
                if (ws) {
                    ws.close();
                }

                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/api/ws/jobs/${jobId}`;

                document.getElementById('status').textContent = `Connecting to ${wsUrl}...`;

                ws = new WebSocket(wsUrl);

                ws.onopen = () => {
                    document.getElementById('status').textContent = 'Connected!';
                    addMessage('System', { type: 'connected', message: 'WebSocket connected' });
                };

                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    addMessage('Server', data);
                };

                ws.onerror = (error) => {
                    document.getElementById('status').textContent = 'Error occurred';
                    addMessage('Error', { type: 'error', message: error.toString() });
                };

                ws.onclose = () => {
                    document.getElementById('status').textContent = 'Disconnected';
                    addMessage('System', { type: 'disconnected', message: 'WebSocket closed' });
                };
            }

            function disconnect() {
                if (ws) {
                    ws.close();
                    ws = null;
                }
            }

            function sendPing() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'ping' }));
                    addMessage('Client', { type: 'ping', message: 'Sent ping' });
                }
            }

            function getStatus() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'get_status' }));
                    addMessage('Client', { type: 'request', message: 'Requested status' });
                }
            }

            function addMessage(source, data) {
                const messagesDiv = document.getElementById('messages');
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${data.type || ''}`;
                messageDiv.innerHTML = `<strong>${source}:</strong> ${JSON.stringify(data, null, 2)}`;
                messagesDiv.appendChild(messageDiv);
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            function clearMessages() {
                document.getElementById('messages').innerHTML = '';
            }
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)
