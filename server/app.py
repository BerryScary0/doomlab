# server/app.py
import math, time, asyncio, random, sqlite3, os
from dataclasses import dataclass
import socketio
from fastapi import FastAPI
from starlette.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest

# ------------- Config / Rules -------------
TICK_HZ = 20          # snapshot rate
BOT_HZ  = 20          # physics/bot step
SPEED   = 4.0         # m/s player
BOT_SPEED = 3.2       # m/s bot
PICKUP_RADIUS = 0.8   # meters
BOT_HIT_RADIUS = 0.7
RESPAWN_POS = (0.5, 1.6, 0.5)    # spawn at maze start
RUN_GOAL_NEAR = 1.2              # distance to spawn to finish
START_LIVES = 5

# ------------- Socket/FastAPI -------------
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
asgi = socketio.ASGIApp(sio, app)

# ------------- DB (SQLite) -------------
DB_PATH = os.path.join(os.path.dirname(__file__), "leaderboard.db")
def db_init():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        duration_ms INTEGER NOT NULL,
        collected INTEGER NOT NULL,
        total_needed INTEGER NOT NULL,
        ts INTEGER NOT NULL
    )""")
    con.commit(); con.close()
db_init()

# ------------- World Types -------------
@dataclass
class Player:
    x: float; y: float; z: float; yaw: float
    lives: int; alive: bool
    _t: float
    in_f: bool=False; in_b: bool=False; in_l: bool=False; in_r: bool=False
    collected: int=0; started_at: float=0.0; finished: bool=False
    name: str = "player"

@dataclass
class Pickup:
    x: float; y: float; z: float; taken_by: str|None=None

@dataclass
class Bot:
    x: float; y: float; z: float; yaw: float; wander_t: float=0.0

WORLD = {
    "players": {},           # sid -> Player
    "maze": None,            # { "walls":[[x0,z0,x1,z1],...], "start":(x,z), "goal":(x,z) }
    "pickups": [],           # list[Pickup]
    "bots": [],              # list[Bot]
    "active_run": False,     # any player has started (picked up first item)
    "total_needed": 0,
}

# ------------------ Connected Pac-Man style maze generator ------------------
# ---------------- Interconnected, sealed-border maze ----------------
# bit masks
N, S, E, W = 1, 2, 4, 8
DX = {E: 1, W: -1, N: 0, S: 0}
DY = {E: 0, W:  0, N: -1, S: 1}
OPP = {E: W, W: E, N: S, S: N}

def gen_maze(cols=17, rows=11, cell=2.5, loop_chance=0.42, min_degree=2, seed=None):
    """
    Fully connected 'Pac-Man-ish' maze:
      - DFS perfect maze
      - add many loops (loop_chance)
      - ensure each cell has at least `min_degree` openings (fewer dead-ends)
      - sealed border (no outer gaps)
    Returns: {"walls": [[x0,z0,x1,z1], ...], "cell", "cols", "rows", "start", "goal", "carve"}
    """
    import random
    rng = random.Random(seed)

    # 1) perfect maze by randomized DFS
    carve = [[0]*cols for _ in range(rows)]
    seen  = [[False]*cols for _ in range(rows)]
    st = [(0, 0)]
    seen[0][0] = True
    while st:
        x, y = st[-1]
        choices = []
        for d in (N, S, E, W):
            nx, ny = x + DX[d], y + DY[d]
            if 0 <= nx < cols and 0 <= ny < rows and not seen[ny][nx]:
                choices.append(d)
        if choices:
            d = rng.choice(choices)
            nx, ny = x + DX[d], y + DY[d]
            carve[y][x]   |= d
            carve[ny][nx] |= OPP[d]
            seen[ny][nx]   = True
            st.append((nx, ny))
        else:
            st.pop()

    # 2) add loops (make it more interconnected / fewer walls overall)
    for y in range(rows):
        for x in range(cols):
            for d in (E, S):  # avoid dup
                nx, ny = x + DX[d], y + DY[d]
                if 0 <= nx < cols and 0 <= ny < rows:
                    if not (carve[y][x] & d) and not (carve[ny][nx] & OPP[d]):
                        if rng.random() < loop_chance:
                            carve[y][x]   |= d
                            carve[ny][nx] |= OPP[d]

    # 3) ensure min degree (reduce dead-ends even more)
    def deg(cx, cy):
        c = carve[cy][cx]
        return int(bool(c & N)) + int(bool(c & S)) + int(bool(c & E)) + int(bool(c & W))
    for y in range(rows):
        for x in range(cols):
            while deg(x, y) < min_degree:
                candidates = []
                if x+1 < cols: candidates.append(E)
                if x-1 >= 0:   candidates.append(W)
                if y+1 < rows: candidates.append(S)
                if y-1 >= 0:   candidates.append(N)
                if not candidates: break
                d = rng.choice(candidates)
                nx, ny = x + DX[d], y + DY[d]
                carve[y][x]   |= d
                carve[ny][nx] |= OPP[d]

    # 4) convert passages to *edge* walls (sealed border, no gates)
    ox = - (cols * cell) * 0.5
    oz = - (rows * cell) * 0.5
    walls = set()

    # full frame
    for y in range(rows):
        z0 = oz + y*cell
        z1 = z0 + cell
        for x in range(cols):
            x0 = ox + x*cell
            x1 = x0 + cell
            walls.add((round(x0,4), round(z0,4), round(x1,4), round(z0,4)))  # N
            walls.add((round(x0,4), round(z0,4), round(x0,4), round(z1,4)))  # W
            if y == rows-1:  # S outer
                walls.add((round(x0,4), round(z1,4), round(x1,4), round(z1,4)))
            if x == cols-1:  # E outer
                walls.add((round(x1,4), round(z0,4), round(x1,4), round(z1,4)))

    # remove edges where we have passages
    for y in range(rows):
        for x in range(cols):
            x0 = ox + x*cell
            z0 = oz + y*cell
            if carve[y][x] & E:
                walls.discard((round(x0+cell,4), round(z0,4), round(x0+cell,4), round(z0+cell,4)))
            if carve[y][x] & S:
                walls.discard((round(x0,4), round(z0+cell,4), round(x0+cell,4), round(z0+cell,4)))

    start = (ox + 0.5*cell,           oz + 0.5*cell)            # near top-left
    goal  = (ox + cols*cell - 0.5*cell, oz + rows*cell - 0.5*cell)  # near bottom-right

    return {
        "walls": [list(s) for s in walls],
        "cell": cell, "cols": cols, "rows": rows,
        "start": start, "goal": goal,
        "carve": carve
    }
# --------------------------------------------------------------------



def _walkable_cells(maze):
    # all cells are walkable centers; passages are in carve bitmask.
    cols, rows, cell = maze["cols"], maze["rows"], maze["cell"]
    ox = - (cols * cell) * 0.5
    oz = - (rows * cell) * 0.5
    for y in range(rows):
        for x in range(cols):
            # every cell center works; corridors exist between cells
            wx = ox + (x + 0.5) * cell
            wz = oz + (y + 0.5) * cell
            yield (x, y, wx, wz)

def place_pickups(maze, n=5):
    rng = random.Random()
    cells = list(_walkable_cells(maze))
    rng.shuffle(cells)
    picks = []
    for _, _, wx, wz in cells[:max(0, n)]:
        picks.append(Pickup(x=float(wx), y=0.0, z=float(wz)))
    return picks

def spawn_bots(maze, n=3):
    rng = random.Random()
    cells = list(_walkable_cells(maze))
    rng.shuffle(cells)
    bots = []
    for _, _, wx, wz in cells[:max(0, n)]:
        bots.append(Bot(x=wx, y=0.0, z=wz, yaw=rng.uniform(-math.pi, math.pi)))
    return bots

def ensure_world():
    if WORLD["maze"] is None:
        WORLD["maze"] = gen_maze(cols=17, rows=11, cell=2.5, loop_chance=0.42, min_degree=2)
        WORLD["pickups"] = place_pickups(WORLD["maze"], n=5)
        WORLD["bots"]    = spawn_bots(WORLD["maze"], n=3)
        WORLD["active_run"] = False
        WORLD["total_needed"] = len(WORLD["pickups"])


ensure_world()

# ------------- Helpers -------------
def dist2(x1,z1,x2,z2): 
    dx, dz = x1-x2, z1-z2
    return dx*dx + dz*dz

def respawn_player(p: Player):
    sx, sz = WORLD["maze"]["start"]
    p.x, p.y, p.z = (sx, 1.6, sz)
    p.alive = True
    p.yaw = 0.0

def late_join_spawn() -> tuple[float,float,float]:
    sx, sz = WORLD["maze"]["start"]; gx, gz = WORLD["maze"]["goal"]
    if WORLD["active_run"]:
        return (gx, 1.6, gz)
    return (sx, 1.6, sz)

def maybe_finish_run(p:Player):
    # finished if collected all and returned to spawn vicinity
    if p.collected >= WORLD["total_needed"]:
        sx,sz = WORLD["maze"]["start"]
        if dist2(p.x, p.z, sx, sz) <= RUN_GOAL_NEAR*RUN_GOAL_NEAR:
            if p.started_at > 0 and not p.finished:
                duration_ms = int((time.time() - p.started_at) * 1000)
                p.finished = True
                # write leaderboard row
                con = sqlite3.connect(DB_PATH)
                con.execute("INSERT INTO runs(name,duration_ms,collected,total_needed,ts) VALUES(?,?,?,?,?)",
                            (p.name, duration_ms, p.collected, WORLD["total_needed"], int(time.time())))
                con.commit(); con.close()
                print(f"[leaderboard] {p.name} finished in {duration_ms} ms")

# ------------- Socket events -------------
@sio.event
async def connect(sid, environ):
    ensure_world()
    # Spawn based on join rule
    x,y,z = late_join_spawn()
    WORLD["players"][sid] = Player(x=x,y=y,z=z,yaw=0.0,lives=START_LIVES,alive=True,_t=time.time(),name=f"p{sid[:4]}")
    # Send one-time world description (maze, pickups initial)
    await sio.emit("world", {
        "maze": WORLD["maze"],
        "pickups": [{"x":p.x,"y":p.y,"z":p.z,"taken_by":p.taken_by} for p in WORLD["pickups"]],
        "total_needed": WORLD["total_needed"]
    }, to=sid)
    # Tell them who they are
    await sio.emit("hello", {"sid": sid}, to=sid)

@sio.event
async def disconnect(sid):
    WORLD["players"].pop(sid, None)

@sio.on("input")
async def on_input(sid, data):
    p:Player = WORLD["players"].get(sid)
    if not p: return
    if not p.alive:
        # ignore movement until respawned
        p._t = time.time()
        return

    # inputs + yaw
    p.in_f = bool(data.get("f")); p.in_b = bool(data.get("b"))
    p.in_l = bool(data.get("l")); p.in_r = bool(data.get("r"))
    p.yaw  = float(data.get("yaw", p.yaw))

    # server dt (allow up to 200ms so late packets don't slow ghost)
    now = time.time()
    dt = now - p._t; p._t = now
    if dt < 0: dt = 0.0
    if dt > 0.20: dt = 0.20

    # if no input, don’t integrate; prevents idle catch-up
    if not (p.in_f or p.in_b or p.in_l or p.in_r):
        return

    # basis from yaw (must match client’s forward/right)
    fx, fz = -math.sin(p.yaw), -math.cos(p.yaw)  # forward
    rx, rz =  math.cos(p.yaw), -math.sin(p.yaw)  # right

    vx = vz = 0.0
    if p.in_f: vx += fx; vz += fz
    if p.in_b: vx -= fx; vz -= fz
    if p.in_r: vx += rx; vz += rz
    if p.in_l: vx -= rx; vz -= rz

    mag = (vx*vx + vz*vz) ** 0.5
    if mag > 0.0:
        vx = vx / mag * SPEED
        vz = vz / mag * SPEED
        p.x += vx * dt
        p.z += vz * dt

    # pickups (authoritative): first pickup → start timer, each within radius → collect
    for pick in WORLD["pickups"]:
        if pick.taken_by is None and dist2(p.x, p.z, pick.x, pick.z) <= PICKUP_RADIUS*PICKUP_RADIUS:
            pick.taken_by = sid
            p.collected += 1
            if p.started_at == 0.0:
                p.started_at = time.time()
                WORLD["active_run"] = True
            await sio.emit("pickup_taken", {"id": WORLD["pickups"].index(pick), "by": sid})

    # check finish
    maybe_finish_run(p)

# ---- Bot pathing helpers (grid-based on the maze carve) ----
def world_to_cell(x, z, maze):
    cell = maze["cell"]; cols, rows = maze["cols"], maze["rows"]
    ox = - (cols * cell) * 0.5; oz = - (rows * cell) * 0.5
    cx = int((x - ox) / cell); cz = int((z - oz) / cell)
    # clamp to grid
    if cx < 0: cx = 0
    if cz < 0: cz = 0
    if cx > cols - 1: cx = cols - 1
    if cz > rows - 1: cz = rows - 1
    return cx, cz

def cell_center(cx, cz, maze):
    cell = maze["cell"]; cols, rows = maze["cols"], maze["rows"]
    ox = - (cols * cell) * 0.5; oz = - (rows * cell) * 0.5
    return (ox + (cx + 0.5) * cell, oz + (cz + 0.5) * cell)

def neighbors_from_carve(cx, cz, carve, cols, rows):
    neigh = []
    # follow carved passages (bitmask N,S,E,W)
    if carve[cz][cx] & E and cx+1 < cols: neigh.append((cx+1, cz))
    if carve[cz][cx] & W and cx-1 >= 0:  neigh.append((cx-1, cz))
    if carve[cz][cx] & S and cz+1 < rows: neigh.append((cx, cz+1))
    if carve[cz][cx] & N and cz-1 >= 0:  neigh.append((cx, cz-1))
    return neigh

from collections import deque
def bfs_path(maze, start_c, goal_c):
    cols, rows = maze["cols"], maze["rows"]
    carve = maze["carve"]
    sx, sz = start_c; gx, gz = goal_c
    if not (0 <= sx < cols and 0 <= sz < rows and 0 <= gx < cols and 0 <= gz < rows):
        return []
    q = deque([(sx, sz)])
    came = { (sx, sz): None }
    while q:
        x, z = q.popleft()
        if (x, z) == (gx, gz):
            break
        for nx, nz in neighbors_from_carve(x, z, carve, cols, rows):
            if (nx, nz) not in came:
                came[(nx, nz)] = (x, z)
                q.append((nx, nz))
    if (gx, gz) not in came:
        return []
    # reconstruct path
    path = []
    cur = (gx, gz)
    while cur is not None:
        path.append(cur)
        cur = came[cur]
    path.reverse()
    return path


# ------------- Bots -------------
async def bot_loop():
    dt = 1.0 / BOT_HZ
    CHASE_RADIUS = 12.0  # meters
    while True:
        start = time.time()

        maze = WORLD["maze"]
        if maze is not None:
            cols, rows = maze["cols"], maze["rows"]

            # find nearest player per bot and move along grid path
            players_list = [p for p in WORLD["players"].values() if p.alive]
            for b in WORLD["bots"]:
                if players_list:
                    # nearest player in world space
                    px, pz = min(((p.x, p.z) for p in players_list),
                                 key=lambda P: (P[0]-b.x)**2 + (P[1]-b.z)**2)
                    dx = px - b.x; dz = pz - b.z
                    if dx*dx + dz*dz <= CHASE_RADIUS*CHASE_RADIUS:
                        # path on grid toward player
                        bs = world_to_cell(b.x, b.z, maze)
                        gs = world_to_cell(px, pz, maze)
                        path = bfs_path(maze, bs, gs)
                        if len(path) >= 2:
                            nx, nz = path[1]
                            tx, tz = cell_center(nx, nz, maze)
                            yaw = math.atan2(tx - b.x, tz - b.z)
                            b.yaw = yaw
                            b.x += math.sin(yaw) * BOT_SPEED * dt
                            b.z += math.cos(yaw) * BOT_SPEED * dt
                            continue  # chased this frame

                # wander along current yaw if no chase target
                b.wander_t -= dt
                if b.wander_t <= 0:
                    # pick a random open neighbor direction from current cell
                    cx, cz = world_to_cell(b.x, b.z, maze)
                    opts = list(neighbors_from_carve(cx, cz, maze["carve"], cols, rows))
                    if opts:
                        nx, nz = random.choice(opts)
                        tx, tz = cell_center(nx, nz, maze)
                        b.yaw = math.atan2(tx - b.x, tz - b.z)
                    else:
                        b.yaw = random.uniform(-math.pi, math.pi)
                    b.wander_t = random.uniform(0.8, 2.0)

                b.x += math.sin(b.yaw) * BOT_SPEED * dt
                b.z += math.cos(b.yaw) * BOT_SPEED * dt

        # damage check unchanged
        for sid, p in list(WORLD["players"].items()):
            if not p.alive: continue
            for b in WORLD["bots"]:
                if dist2(p.x, p.z, b.x, b.z) <= BOT_HIT_RADIUS*BOT_HIT_RADIUS:
                    p.lives -= 1
                    p.alive = False
                    await sio.emit("death", {"sid": sid, "lives": p.lives})
                    if p.lives > 0:
                        async def _respawn(sid_=sid):
                            await asyncio.sleep(1.0)
                            q = WORLD["players"].get(sid_)
                            if q:
                                respawn_player(q); q.alive = True
                                await sio.emit("respawn", {"sid": sid_})
                        asyncio.create_task(_respawn())
                    break

        # timing
        elapsed = time.time() - start
        await asyncio.sleep(max(0.0, dt - elapsed))


# ------------- Snapshots & API -------------
async def snapshot_loop():
    interval = 1.0 / TICK_HZ
    while True:
        await sio.emit("snapshot", {
            "players": { sid: {"x":p.x,"y":p.y,"z":p.z,"yaw":p.yaw,"lives":p.lives,"alive":p.alive,"collected":p.collected}
                         for sid,p in WORLD["players"].items() },
            "bots": [ {"x":b.x,"y":0.0,"z":b.z,"yaw":b.yaw} for b in WORLD["bots"] ],
            "pickups": [{"x":pk.x,"y":pk.y,"z":pk.z,"taken_by":pk.taken_by} for pk in WORLD["pickups"]],
            "total_needed": WORLD["total_needed"]
        })
        await asyncio.sleep(interval)

@app.get("/leaderboard")
def leaderboard():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT name,duration_ms,collected,total_needed,ts FROM runs ORDER BY duration_ms ASC LIMIT 20").fetchall()
    con.close()
    return JSONResponse([{"name":r[0], "duration_ms":r[1], "collected":r[2], "total_needed":r[3], "ts":r[4]} for r in rows])

@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain; version=0.0.4")

@app.on_event("startup")
async def on_start():
    ensure_world()
    asyncio.create_task(snapshot_loop())
    asyncio.create_task(bot_loop())
