# server/app.py
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import socketio
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# --- Socket.IO (real-time) ---
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# --- FastAPI (HTTP routes) ---
api = FastAPI()

# Metric example (we'll use it later)
connections_total = Counter("connections_total", "Total Socket.IO connections")

@sio.event
async def connect(sid, environ):
    connections_total.inc()
    print(f"[sio] client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[sio] client disconnected: {sid}")

# Simple echo to prove round-trip later
@sio.event
async def ping(sid, data):
    await sio.emit("pong", {"got": data}, to=sid)

@api.get("/health")
def health():
    return {"status": "ok"}

@api.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"),
                             media_type=CONTENT_TYPE_LATEST)

# Mount FastAPI under Socket.IO
app_sio = socketio.ASGIApp(sio, other_asgi_app=api)
