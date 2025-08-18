# DoomLab FPS

## How to run
To run DoomLab locally right now:

1️ Start the backend
In PowerShell, from your doomlab/server folder:

# Activate your virtual environment
.venv\Scripts\Activate

# Run FastAPI + Socket.IO server

cd server

uvicorn app:asgi --reload --host 0.0.0.0 --port 8000


If it’s running right, you’ll see something like:

INFO:     Uvicorn running on http://0.0.0.0:8000


2️ Start the frontend
In a separate PowerShell window, get to doomlab/web folder, from there:

cd web

python -m http.server 8080


This will serve index.html and game.js over http://localhost:8080.

3️ Open in browser

Go to: http://localhost:8080

Click anywhere in the game window to lock the mouse.

Move with WASD and look around with the mouse.

## Repo layout
- server/ - FastAPI + Socket.IO authoritative server
- web/ - static frontend (CDN scripts, no build)
- infra/ - Terraform IaC
- scripts/ - start/stop/deploy helpers

## Approach
- Start simple (KISS), avoid over-engineering (YAGNI), reuse where possible (DRY).
- Monorepo for now: easier for solo dev.
- Server authoritative: clients send input; server sends snapshots.

## Milestones
- v0.1.0: Minimal backend + frontend can connect
- v0.2.0: Basic movement + map

