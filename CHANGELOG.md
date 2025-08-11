# Changelog

All notable changes to this project will be documented in this file.  
This project follows [Semantic Versioning](https://semver.org/).

---

## [v0.0.1] - 2025-08-11

### Added
- **First playable FPS loop** with working `PointerLockControls` for mouse-look.
- Basic WASD movement with camera-relative forward/back and strafe controls.
- FastAPI + Socket.IO backend with authoritative server-side position tracking.
- Server broadcasts snapshots to all connected clients at 15 Hz.
- Client-side ghost rendering for server-authoritative reconciliation.

### Fixed
- Aligned client and server movement basis so yaw and strafe directions match perfectly.
- Prevented unintended roll/tilt when moving the mouse rapidly.
- Adjusted server `dt` handling to prevent ghost moving slower than the player.
- Matched movement speed for local player and server ghost to eliminate drift.

### Notes
- Snapshot tick rate remains **15 Hz** for now.
- Inputs are sent every frame for smooth motion sync.
- No collision or combat mechanics yet — these will come in later milestones.
