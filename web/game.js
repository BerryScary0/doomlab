import * as THREE from 'three';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';

// --- Three basics ---
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

const camera = new THREE.PerspectiveCamera(
  75, window.innerWidth / window.innerHeight, 0.1, 1000
);
// Important: FPS camera expects YXZ (yaw → pitch), zeroed roll.
camera.rotation.set(0, 0, 0);
camera.rotation.order = 'YXZ';

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// --- Simple world (ground + cube landmark) ---
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(100, 100),
  new THREE.MeshBasicMaterial({ color: 0x202020, side: THREE.DoubleSide })
);
floor.rotation.x = -Math.PI / 2;
scene.add(floor);

// add a grid to visualize the ground
const WORLD = {
  minX: -45, maxX: 45,
  minZ: -45, maxZ: 45,
  groundY: 0
};

function addFence() {
  const mat = new THREE.LineBasicMaterial({ color: 0x4444ff });
  const g = new THREE.BufferGeometry();
  const x0 = WORLD.minX, x1 = WORLD.maxX, z0 = WORLD.minZ, z1 = WORLD.maxZ, y = 0.01;
  const pts = [
    new THREE.Vector3(x0, y, z0), new THREE.Vector3(x1, y, z0),
    new THREE.Vector3(x1, y, z1), new THREE.Vector3(x0, y, z1),
    new THREE.Vector3(x0, y, z0)
  ];
  g.setFromPoints(pts);
  const line = new THREE.Line(g, mat);
  scene.add(line);
}
addFence();


const cube = new THREE.Mesh(
  new THREE.BoxGeometry(1, 1, 1),
  new THREE.MeshBasicMaterial({ color: 0x00ff00 })
);
cube.position.set(3, 0.5, -5);
scene.add(cube);



// === BIG MAZE WALLS (merged + trimmed at corners) ===================
const WALL_HEIGHT    = 2.4;
const WALL_THICKNESS = 0.30;
// extra clearance at corners (on top of half-thickness). Bump if you want wider gaps.
const TRIM_EXTRA     = 0.12;
const EPS            = 1e-4;

// Use Standard if you already added lights; swap to MeshBasicMaterial if not.
const wallMaterial = new THREE.MeshBasicMaterial({ color: 0x5a84ff });

const wallGroup = new THREE.Group();
scene.add(wallGroup);

// --- helpers ---
function roundKey(v) { return Math.round(v * 1000) / 1000; }
function key(x, z)    { return `${roundKey(x)}|${roundKey(z)}`; }

function normalizeSeg([x0, z0, x1, z1]) {
  const dx = x1 - x0, dz = z1 - z0;
  // assume maze is axis-aligned; choose orientation by dominant axis
  if (Math.abs(dx) >= Math.abs(dz)) {
    // horizontal (sort left->right)
    if (x1 < x0) { [x0, x1] = [x1, x0]; [z0, z1] = [z1, z0]; }
    return { o:'H', x0, z0, x1, z1 };
  } else {
    // vertical (sort bottom->top)
    if (z1 < z0) { [x0, x1] = [x1, x0]; [z0, z1] = [z1, z0]; }
    return { o:'V', x0, z0, x1, z1 };
  }
}

function mergeColinear(segs) {
  // group by orientation + shared constant axis (x for vertical, z for horizontal)
  const buckets = new Map();
  for (const s of segs) {
    const r = normalizeSeg(s);
    const axisVal = r.o === 'H' ? roundKey(r.z0) : roundKey(r.x0);
    const k = `${r.o}|${axisVal}`;
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(r);
  }

  const merged = [];
  for (const [k, arr] of buckets) {
    if (!arr.length) continue;
    // sort along running axis
    if (arr[0].o === 'H') arr.sort((a,b) => a.x0 - b.x0);
    else                  arr.sort((a,b) => a.z0 - b.z0);

    // sweep-merge overlapping/contiguous
    let cur = arr[0];
    for (let i = 1; i < arr.length; i++) {
      const s = arr[i];
      if (cur.o === 'H') {
        // same z line
        if (s.x0 <= cur.x1 + EPS && Math.abs(s.z0 - cur.z0) < EPS) {
          // extend
          cur.x1 = Math.max(cur.x1, s.x1);
        } else {
          merged.push(cur);
          cur = s;
        }
      } else {
        // vertical: same x line
        if (s.z0 <= cur.z1 + EPS && Math.abs(s.x0 - cur.x0) < EPS) {
          cur.z1 = Math.max(cur.z1, s.z1);
        } else {
          merged.push(cur);
          cur = s;
        }
      }
    }
    merged.push(cur);
  }
  // back to simple tuple form
  return merged.map(r => [r.x0, r.z0, r.x1, r.z1]);
}

function buildMaze(maze) {
  wallGroup.clear();
  if (!maze || !Array.isArray(maze.walls)) return;

  // 1) merge to avoid tiny slits along straight runs
  const merged = mergeColinear(maze.walls);

  // 2) global extents (used to detect the outer border)
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const [x0, z0, x1, z1] of merged) {
    minX = Math.min(minX, x0, x1);
    maxX = Math.max(maxX, x0, x1);
    minZ = Math.min(minZ, z0, z1);
    maxZ = Math.max(maxZ, z0, z1);
  }
  const onBorder = (x, z) =>
    Math.abs(x - minX) < 1e-4 || Math.abs(x - maxX) < 1e-4 ||
    Math.abs(z - minZ) < 1e-4 || Math.abs(z - maxZ) < 1e-4;

  // 3) build endpoint junction map (where to trim)
  const ends = new Map(); // key(x,z) -> array of {ux,uz}
  for (const [x0, z0, x1, z1] of merged) {
    const dx = x1 - x0, dz = z1 - z0;
    const len = Math.hypot(dx, dz);
    if (len < 1e-6) continue;
    const ux = dx / len, uz = dz / len;
    const kA = key(x0, z0), kB = key(x1, z1);
    if (!ends.has(kA)) ends.set(kA, []);
    if (!ends.has(kB)) ends.set(kB, []);
    ends.get(kA).push({ ux, uz });
    ends.get(kB).push({ ux: -ux, uz: -uz });
  }

  // 4) emit meshes; trim only at interior junctions (never trim border segments)
  const HALF_T = WALL_THICKNESS * 0.5;
  for (const [x0, z0, x1, z1] of merged) {
    const dx = x1 - x0, dz = z1 - z0;
    let len = Math.hypot(dx, dz);
    if (len < 1e-6) continue;

    const ux = dx / len, uz = dz / len;
    const kA = key(x0, z0), kB = key(x1, z1);

    const meetsA = (ends.get(kA)?.length || 0) > 1;
    const meetsB = (ends.get(kB)?.length || 0) > 1;

    const isAonBorder = onBorder(x0, z0);
    const isBonBorder = onBorder(x1, z1);

    // trim only if it's a junction AND not on the border
    let trimA = (!isAonBorder && meetsA) ? (HALF_T + TRIM_EXTRA) : 0.0;
    let trimB = (!isBonBorder && meetsB) ? (HALF_T + TRIM_EXTRA) : 0.0;

    const inner = Math.max(0.001, len - (trimA + trimB));

    // center shifted by half the trim delta
    const cx = (x0 + x1) * 0.5 + (trimB - trimA) * 0.5 * ux;
    const cz = (z0 + z1) * 0.5 + (trimB - trimA) * 0.5 * uz;

    const geom = new THREE.BoxGeometry(inner + WALL_THICKNESS, WALL_HEIGHT, WALL_THICKNESS);
    const mesh = new THREE.Mesh(geom, wallMaterial);
    mesh.position.set(cx, WALL_HEIGHT / 2, cz);
    mesh.rotation.y = Math.atan2(ux, uz);
    wallGroup.add(mesh);
  }

  // 5) update your simple AABB clamp to the maze extents (prevents walking “outside”)
  WORLD.minX = minX - 0.5;
  WORLD.maxX = maxX + 0.5;
  WORLD.minZ = minZ - 0.5;
  WORLD.maxZ = maxZ + 0.5;
}

// ====================================================================

const pickupGroup = new THREE.Group(); scene.add(pickupGroup);


// --- Bots ---
const botGroup = new THREE.Group();
scene.add(botGroup);
const botGeo = new THREE.ConeGeometry(0.4, 1.0, 10);
const botMat = new THREE.MeshBasicMaterial({ color: 0xff3333, wireframe: true });


function buildPickups(picks) {
  pickupGroup.clear();
  for (const p of picks) {
    if (p.taken_by) continue;
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(0.3, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xffcc00 })
    );
    m.position.set(p.x, 0.3, p.z);
    pickupGroup.add(m);
  }
}

function syncBots(bots = []) {
  botGroup.clear();
  for (const b of bots) {
    const m = new THREE.Mesh(botGeo, botMat);
    m.position.set(b.x, 0.5, b.z);
    m.rotation.y = b.yaw;
    botGroup.add(m);
  }
}


// --- Pointer lock controls (mouse look) ---
const controls = new PointerLockControls(camera, renderer.domElement);
controls.getObject().position.set(0.5, 1.6, 0.5);
scene.add(controls.getObject());

// click anywhere to lock mouse
window.addEventListener('click', () => {
  if (!controls.isLocked) controls.lock();
});

// --- WASD movement state ---
let moveF = false, moveB = false, moveL = false, moveR = false;
const speed = 4.0; // m/s

document.addEventListener('keydown', (e) => {
  switch (e.code) {
    case 'KeyW': case 'ArrowUp':    moveF = true; break;
    case 'KeyS': case 'ArrowDown':  moveB = true; break;
    case 'KeyA': case 'ArrowLeft':  moveL = true; break;
    case 'KeyD': case 'ArrowRight': moveR = true; break;
  }
});
document.addEventListener('keyup', (e) => {
  switch (e.code) {
    case 'KeyW': case 'ArrowUp':    moveF = false; break;
    case 'KeyS': case 'ArrowDown':  moveB = false; break;
    case 'KeyA': case 'ArrowLeft':  moveL = false; break;
    case 'KeyD': case 'ArrowRight': moveR = false; break;
  }
});

// --- Networking handles ---
const netSocket = window.__socket; // from net.js
netSocket.on("world", (data) => {
  if (data.maze) buildMaze(data.maze);
  if (data.pickups) buildPickups(data.pickups);
});

netSocket.on("pickup_taken", (e) => {
  // Rebuild from snapshot next tick; or quick hide:
  buildPickups((window.__lastSnapshot && window.__lastSnapshot.pickups) || []);
});

netSocket.on("snapshot", (snap) => {
  // Keep your existing player updates...
  // Also mirror pickups for quick rebuild:
  window.__lastSnapshot = snap;
  if (snap.pickups) buildPickups(snap.pickups);
  if (snap.bots) syncBots(snap.bots);
});

netSocket.on("hello", ({ sid }) => {
  console.log("you are", sid);
});

netSocket.on("respawn", ({ sid }) => {
  if (!netSocket || sid !== netSocket.id) return;
  // snap camera to server spawn; server will soon confirm in snapshot anyway
  controls.getObject().position.set(0.5, 1.6, 0.5);
  initFromServer = false; // let syncToMe hard-set next tick
});

// Remote players (including our red "ghost" from server)
const others = new Map(); // sid -> Mesh
const otherGeo = new THREE.BoxGeometry(0.6, 1.6, 0.6);
function makeOther(color = 0x3399ff) {
  const m = new THREE.Mesh(otherGeo, new THREE.MeshBasicMaterial({ color }));
  m.position.y = 0;
  return m;
}

// --- Movement vectors (reused) ---
const up = new THREE.Vector3(0, 1, 0);
const dir = new THREE.Vector3();
const right = new THREE.Vector3();
const vel = new THREE.Vector3();

// Optional local → server reconciliation
let initFromServer = false;
const _tmp = new THREE.Vector3();
function syncToMe(me, alpha = 0.12) {
  const obj = controls.getObject();
  if (!initFromServer) {
    obj.position.set(me.x, me.y, me.z);
    obj.rotation.y = me.yaw;
    initFromServer = true;
    return;
  }
  _tmp.set(me.x, me.y, me.z);
  obj.position.lerp(_tmp, alpha);
  const cur = obj.rotation.y;
  let d = me.yaw - cur;
  d = Math.atan2(Math.sin(d), Math.cos(d));
  obj.rotation.y = cur + d * alpha;
}

// --- Main loop ---
let last = performance.now();
function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = (now - last) / 1000;
  last = now;

  if (controls.isLocked) {
    // Forward from camera, flattened on XZ
    camera.getWorldDirection(dir);
    dir.y = 0;
    if (dir.lengthSq() > 0) dir.normalize();

    // Right = forward × up  (matches server basis exactly)
    right.crossVectors(dir, up).normalize();
    
    // Build velocity from inputs
    vel.set(0, 0, 0);
    if (moveF) vel.add(dir);
    if (moveB) vel.sub(dir);
    if (moveR) vel.add(right); // <- canonical (no inversion needed)
    if (moveL) vel.sub(right);

    if (vel.lengthSq() > 0) {
      vel.normalize().multiplyScalar(speed * dt);
      controls.getObject().position.add(vel);

      const obj = controls.getObject().position;
      // keep feet on the “ground”
      obj.y = 1.6; // eye height over y=0 ground

      // clamp to world bounds (simple AABB)
      if (obj.x < WORLD.minX) obj.x = WORLD.minX;
      if (obj.x > WORLD.maxX) obj.x = WORLD.maxX;
      if (obj.z < WORLD.minZ) obj.z = WORLD.minZ;
      if (obj.z > WORLD.maxZ) obj.z = WORLD.maxZ;

    }
     
  }

  // Send inputs every frame (smooth server dt)
  if (controls.isLocked && netSocket && netSocket.connected) {
    const yaw = controls.getObject().rotation.y;
    netSocket.emit("input", {
      f: moveF, b: moveB, l: moveL, r: moveR,
      yaw,
      // If you ever want server to use client basis, uncomment:
      // fwdX: dir.x,  fwdZ: dir.z,
      // rightX: right.x, rightZ: right.z,
      // dt  // we ignore this on server, keeping server-time authority
    });
  }

  // Render
  renderer.render(scene, camera);

  // Apply latest snapshot
  const snap = window.__lastSnapshot;
  if (snap && snap.players) {
    // create/update non-self players
    for (const [sid, p] of Object.entries(snap.players)) {
      if (netSocket && sid === netSocket.id) continue;
      let m = others.get(sid);
      if (!m) {
        m = makeOther();
        scene.add(m);
        others.set(sid, m);
      }
      m.position.set(p.x, p.y, p.z);
      m.rotation.y = p.yaw;
    }

    // ghost for me (server-authoritative pose)
    if (netSocket) {
      const me = snap.players[netSocket.id];
      if (me) {
        if (!others.has(netSocket.id)) {
          const ghost = makeOther(0xff5555);
          ghost.material.transparent = true;
          ghost.material.opacity = 0.35;
          scene.add(ghost);
          others.set(netSocket.id, ghost);
        }
        const ghost = others.get(netSocket.id);
        ghost.position.set(me.x, me.y, me.z);
        ghost.rotation.y = me.yaw;

        // gentle correction when we're noticeably off
        const err = controls.getObject().position.distanceTo(ghost.position);
        if (err > 0.05) syncToMe(me, 0.12);
      }
    }

    // prune
    for (const sid of [...others.keys()]) {
      if (!(sid in snap.players)) {
        const m = others.get(sid);
        scene.remove(m);
        m.geometry.dispose();
        m.material.dispose();
        others.delete(sid);
      }
    }

    window.__lastSnapshot = null;
  }
}
animate();

// resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
