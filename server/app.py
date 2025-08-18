import math, time, asyncio
import socketio
from fastapi import FastAPI
from starlette.responses import PlainTextResponse
from prometheus_client import generate_latest

# --- Socket.IO + FastAPI ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
asgi = socketio.ASGIApp(sio, app)

# --- Minimal world state ---
WORLD = {
    # sid -> {"x","y","z","yaw","lives","alive","_t"}
    "players": {}
}

WORLD_BOUNDS = {
    "minX": -45.0, "maxX": 45.0,
    "minZ": -45.0, "maxZ": 45.0,
    "groundY": 0.0
}

TICK_HZ = 15

def spawn_state():
    now = time.time()
    return {"x": 0.5, "y": 1.6, "z": 0.5, "yaw": 0.0, "lives": 5, "alive": True, "_t": now}

# --- Socket events ---
@sio.event
async def connect(sid, environ):
    WORLD["players"][sid] = spawn_state()
    await sio.emit("hello", {"sid": sid}, to=sid)

@sio.event
async def disconnect(sid):
    WORLD["players"].pop(sid, None)

@sio.on("ping")
async def ping(sid, data):
    await sio.emit("pong", {"ok": True, "at": time.time()}, to=sid)

@sio.on("input")
async def on_input(sid, data):
    p = WORLD["players"].get(sid)
    if not p or not p["alive"]:
        return

    # Inputs
    f = bool(data.get("f")); b = bool(data.get("b"))
    l = bool(data.get("l")); r = bool(data.get("r"))
    yaw = float(data.get("yaw", p.get("yaw", 0.0)))
    p["yaw"] = yaw

    # If no movement keys, don't integrate (and reset time so dt doesn't pile up)
    if not (f or b or l or r):
        p["_t"] = time.time()
        return

    # --- server-time dt ---
    now = time.time()
    dt = now - p.get("_t", now)
    p["_t"] = now
    if dt < 0: dt = 0.0
    if dt > 0.20: dt = 0.20  # allow up to 200ms so late packets don't slow the ghost

    # --- Movement basis (yaw fallback keeps client simple) ---
    # forward = (-sin(yaw), 0, -cos(yaw)); right = (cos(yaw), 0, -sin(yaw))
    fx, fz = -math.sin(yaw), -math.cos(yaw)
    rx, rz =  math.cos(yaw), -math.sin(yaw)

    vx = vz = 0.0
    if f: vx += fx; vz += fz
    if b: vx -= fx; vz -= fz
    if r: vx += rx; vz += rz
    if l: vx -= rx; vz -= rz

    # normalize so diagonals aren't faster
    mag = (vx*vx + vz*vz) ** 0.5
    if mag > 0:
        speed = 4.0
        vx = vx / mag * speed
        vz = vz / mag * speed

    p["x"] = p.get("x", 0.5) + vx * dt
    p["z"] = p.get("z", 0.5) + vz * dt

    # clamp to bounds (authoritative)
    if p["x"] < WORLD_BOUNDS["minX"]: p["x"] = WORLD_BOUNDS["minX"]
    if p["x"] > WORLD_BOUNDS["maxX"]: p["x"] = WORLD_BOUNDS["maxX"]
    if p["z"] < WORLD_BOUNDS["minZ"]: p["z"] = WORLD_BOUNDS["minZ"]
    if p["z"] > WORLD_BOUNDS["maxZ"]: p["z"] = WORLD_BOUNDS["maxZ"]
    p["y"] = 1.6  # keep eye height stable over flat ground


# --- Snapshot loop (share positions) ---
async def snapshot_loop():
    interval = 1.0 / TICK_HZ
    while True:
        await sio.emit("snapshot", {"players": WORLD["players"]})
        await asyncio.sleep(interval)

@app.on_event("startup")
async def on_start():
    asyncio.create_task(snapshot_loop())

# --- Metrics (optional) ---
@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain; version=0.0.4")
