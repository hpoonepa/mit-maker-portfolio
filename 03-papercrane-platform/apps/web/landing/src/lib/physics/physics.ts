import * as THREE from "three";
import { Body } from "./body";

const _normal = new THREE.Vector3();
const _vel = new THREE.Vector3();
const _v1 = new THREE.Vector3();
const _pos = new THREE.Vector3();
const _p1 = new THREE.Vector3();

export class Physics {
  bodies: Body[] = [];
  isActive = true;
  // Stronger pull -> tighter cluster around origin.
  gravityFactor = 45;
  // Per-second velocity retention applied as Math.pow(damping, dt). Lower =
  // more aggressive drag (settle faster). Higher = floatier drift.
  linearDamping = 0.05;
  angularDamping = 0.03;
  // Optional axis-aligned soft walls; bodies bounce off these planes.
  // Set in world units. Bodies can travel slightly inside before bouncing.
  bounds: { x: number; y: number; z: number } | null = null;
  wallRestitution = 0.15;

  update(dt: number): void {
    if (!this.isActive) return;
    const n = this.bodies.length;

    // Pre-pass: resolve pure positional overlaps without exchanging velocity.
    // This unsticks piles that built up from multi-body contact.
    for (let pass = 0; pass < 2; pass++) {
      for (let a = 0; a < n; a++) {
        const ba = this.bodies[a];
        for (let p = a + 1; p < n; p++) {
          const bb = this.bodies[p];
          _normal.copy(ba.position).sub(bb.position);
          const distance = _normal.length();
          const minDist = ba.radius + bb.radius;
          if (distance < minDist && distance > 1e-6) {
            _normal.normalize();
            const overlap = (minDist - distance) * 0.5;
            ba.position.addScaledVector(_normal, overlap);
            bb.position.addScaledVector(_normal, -overlap);
          }
        }
      }
    }

    for (let a = 0; a < n; a++) {
      const ba = this.bodies[a];
      ba.updateGravity(dt, this.gravityFactor);
      _vel.copy(ba.velocity);
      _pos.copy(ba.position);

      for (let p = a + 1; p < n; p++) {
        const bb = this.bodies[p];
        _v1.copy(bb.velocity);
        _p1.copy(bb.position);
        _normal.copy(_pos).sub(_p1);
        const distance = _normal.length();
        const minDist = ba.radius + bb.radius;
        if (distance < minDist && distance > 1e-6) {
          const sharedFriction = Math.sqrt(ba.friction * bb.friction);
          ba.frictionTot += sharedFriction;
          bb.frictionTot += sharedFriction;

          _normal.normalize();
          // Spring-style soft push: split overlap, scale by 0.7 so the impulse
          // doesn't snap bodies apart aggressively in a single frame.
          const overlap = (minDist - distance) * 0.5 * 0.7;
          _pos.addScaledVector(_normal, overlap);
          _p1.addScaledVector(_normal, -overlap);

          // Only resolve velocity along the collision normal IF bodies are
          // approaching each other. Avoids re-pushing already-separating bodies.
          const va = _vel.dot(_normal);
          const vb = _v1.dot(_normal);
          if (va - vb < 0) {
            const ma = ba.mass;
            const mb = bb.mass;
            const e = (ba.restitution + bb.restitution) * 0.5;
            const newVa = (ma * va + mb * vb - mb * (va - vb) * e) / (ma + mb);
            const newVb = (ma * va + mb * vb + ma * (va - vb) * e) / (ma + mb);
            _vel.addScaledVector(_normal, (newVa - va) * 0.6);
            _v1.addScaledVector(_normal, (newVb - vb) * 0.6);
          }

          ba.position.copy(_pos);
          ba.velocity.copy(_vel);
          bb.position.copy(_p1);
          bb.velocity.copy(_v1);
        }
      }

      ba.position.addScaledVector(ba.velocity, dt);
      ba.updateRotation(dt);
      // Air-drag — configurable so individual stages can tune floatiness.
      ba.velocity.multiplyScalar(Math.pow(this.linearDamping, dt));
      ba.angularVelocity.multiplyScalar(Math.pow(this.angularDamping, dt));
      // Snap to rest below threshold to kill last-frame numerical jitter.
      if (ba.velocity.lengthSq() < 0.0004) ba.velocity.set(0, 0, 0);
      if (ba.angularVelocity.lengthSq() < 0.001) ba.angularVelocity.set(0, 0, 0);

      if (this.bounds) {
        const r = ba.radius;
        const bx = this.bounds.x - r;
        const by = this.bounds.y - r;
        // Clamp z tighter than xy so bodies can't approach camera near-plane.
        const bzMax = this.bounds.z - r;
        const bzMin = -this.bounds.z;
        if (ba.position.x > bx) {
          ba.position.x = bx;
          if (ba.velocity.x > 0) ba.velocity.x *= -this.wallRestitution;
        } else if (ba.position.x < -bx) {
          ba.position.x = -bx;
          if (ba.velocity.x < 0) ba.velocity.x *= -this.wallRestitution;
        }
        if (ba.position.y > by) {
          ba.position.y = by;
          if (ba.velocity.y > 0) ba.velocity.y *= -this.wallRestitution;
        } else if (ba.position.y < -by) {
          ba.position.y = -by;
          if (ba.velocity.y < 0) ba.velocity.y *= -this.wallRestitution;
        }
        if (ba.position.z > bzMax) {
          ba.position.z = bzMax;
          if (ba.velocity.z > 0) ba.velocity.z *= -this.wallRestitution;
        } else if (ba.position.z < bzMin) {
          ba.position.z = bzMin;
          if (ba.velocity.z < 0) ba.velocity.z *= -this.wallRestitution;
        }
      }
    }
  }

  reset(): void {
    for (const b of this.bodies) b.reset();
  }
}
