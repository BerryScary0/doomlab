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

const cube = new THREE.Mesh(
  new THREE.BoxGeometry(1, 1, 1),
  new THREE.MeshBasicMaterial({ color: 0x00ff00 })
);
cube.position.set(3, 0.5, -5);
scene.add(cube);

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
