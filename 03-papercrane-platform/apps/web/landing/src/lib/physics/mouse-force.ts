import * as THREE from "three";
import type { Body } from "./body";

// Verified from Lusion's bundle (HomeBalloonsPhysics class).
const MOUSE_INFLUENCE = 0.1;
const MOUSE_PUSH_FORCE = 0.12;

const _ndcDir = new THREE.Vector3();
const _wPrev = new THREE.Vector3();
const _wCurr = new THREE.Vector3();
const _delta = new THREE.Vector3();
const _toBody = new THREE.Vector3();

function projectNDCtoZ0(
  ndcX: number,
  ndcY: number,
  camera: THREE.PerspectiveCamera,
  out: THREE.Vector3,
): void {
  out.set(ndcX, ndcY, 0.5).unproject(camera);
  _ndcDir.copy(out).sub(camera.position).normalize();
  if (Math.abs(_ndcDir.z) < 1e-6) {
    out.set(0, 0, 0);
    return;
  }
  const t = -camera.position.z / _ndcDir.z;
  out.copy(camera.position).addScaledVector(_ndcDir, t);
}

function smoothstep(t: number): number {
  // Cubic Hermite (smoothstep) — gentle in, gentle out
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return t * t * (3 - 2 * t);
}

export class MouseForce {
  ndcCurrent = new THREE.Vector2(0, 0);
  ndcLast = new THREE.Vector2(0, 0);
  hasInteraction = false;
  influenceRadius = 3.2;
  // Calmer base strength so cursor motion nudges rather than launches.
  // Still scales with mouse speed (no cap) but with a gentler base.
  forceScale = 14.5;

  bind(): void {
    window.addEventListener("pointermove", (e) => {
      this.ndcCurrent.x = (e.clientX / window.innerWidth) * 2 - 1;
      this.ndcCurrent.y = -(e.clientY / window.innerHeight) * 2 + 1;
      if (!this.hasInteraction) {
        this.ndcLast.copy(this.ndcCurrent);
        this.hasInteraction = true;
      }
    });
  }

  apply(bodies: Body[], camera: THREE.PerspectiveCamera): void {
    if (!this.hasInteraction) return;
    projectNDCtoZ0(this.ndcLast.x, this.ndcLast.y, camera, _wPrev);
    projectNDCtoZ0(this.ndcCurrent.x, this.ndcCurrent.y, camera, _wCurr);
    _delta.copy(_wCurr).sub(_wPrev);

    if (_delta.lengthSq() < 1e-8) {
      this.ndcLast.copy(this.ndcCurrent);
      return;
    }

    const deltaLen = _delta.length();
    // Linear speed scaling, calmer multiplier than before.
    const speedMul = deltaLen * 4;

    for (const body of bodies) {
      _toBody.copy(body.position).sub(_wCurr);
      const dist = _toBody.length();
      const range = body.radius + this.influenceRadius;
      if (dist < range) {
        const falloff = smoothstep(1 - dist / range);
        const radialPush = falloff * MOUSE_PUSH_FORCE * this.forceScale * speedMul;
        body.velocity.addScaledVector(_toBody.normalize(), radialPush);
        // Tangential swipe in mouse-direction — proportional to mouse speed.
        const tangential = falloff * MOUSE_INFLUENCE * this.forceScale * 0.4 * speedMul;
        body.velocity.addScaledVector(_delta, tangential);
        // Subtle tumble; gentler than the previous coefficient so bodies don't
        // spin frantically when grazed.
        const k = falloff * 0.6 * speedMul;
        body.angularVelocity.x += (Math.random() - 0.5) * k;
        body.angularVelocity.y += (Math.random() - 0.5) * k;
        body.angularVelocity.z += (Math.random() - 0.5) * k;
      }
    }
    this.ndcLast.copy(this.ndcCurrent);
  }
}
