# DoomLab FPS

## Repo layout
- server/ — FastAPI + Socket.IO authoritative server
- web/ — static frontend (CDN scripts, no build)
- infra/ — Terraform IaC
- scripts/ — start/stop/deploy helpers

## Approach
- Start simple (KISS), avoid over-engineering (YAGNI), reuse where possible (DRY).
- Monorepo for now: easier for solo dev.
- Server authoritative: clients send input; server sends snapshots.

## Milestones
- v0.1.0: Minimal backend + frontend can connect
- v0.2.0: Basic movement + map

