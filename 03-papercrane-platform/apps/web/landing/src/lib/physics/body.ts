import * as THREE from "three";

const _spinAxis = new THREE.Vector3();
const _spinQuat = new THREE.Quaternion();

export class Body {
  position0 = new THREE.Vector3();
  velocity0 = new THREE.Vector3();
  position = new THREE.Vector3();
  velocity = new THREE.Vector3();
  gravityAcc = new THREE.Vector3();
  gravityForce = new THREE.Vector3();
  angularVelocity = new THREE.Vector3();
  quaternion = new THREE.Quaternion();
  radius = 1;
  mass = 1;
  density = 1;
  friction = 2;
  frictionTot = 0;
  restitution = 0.8;

  constructor(
    radius = 1,
    density = 1,
    friction = 2,
    restitution = 0.8,
    isSemitransparent = false,
    rand: () => number = Math.random,
  ) {
    // Smaller spawn box that roughly matches the visible volume so bodies
    // settle distributed across the frame instead of all converging on origin.
    this.position0.set(
      (rand() - 0.5) * 8,
      (rand() - 0.5) * 5.5,
      isSemitransparent ? 2 + rand() : (rand() - 0.5) * 4,
    );
    this.velocity0.copy(this.position0).multiplyScalar(-0.4);
    this.position.copy(this.position0);
    this.velocity.copy(this.velocity0);

    this.radius = 1.0 * radius;
    this.density = density;
    this.friction = friction;
    this.restitution = restitution;
    const volume = Math.PI * this.radius * 1.333333;
    this.mass = volume * this.radius * this.radius * this.density;

    this.angularVelocity.set(
      (rand() - 0.5) * 4,
      (rand() - 0.5) * 4,
      (rand() - 0.5) * 4,
    );
  }

  reset(): void {
    this.position.copy(this.position0);
    this.velocity.copy(this.velocity0);
  }

  updateGravity(dt: number, gravityFactor: number): void {
    // Gravity is gated by distance from origin: when a body is already at the
    // resting radius (~0.5 unit from center for our pile), don't keep pumping it.
    const distSq = this.position.lengthSq();
    if (distSq < 0.04) {
      this.frictionTot = 0;
      return;
    }
    this.gravityForce.copy(this.position).negate().multiplyScalar(gravityFactor);
    this.gravityAcc.copy(this.gravityForce).multiplyScalar(1 / this.mass);
    this.gravityAcc.multiplyScalar(1 / (1 + this.frictionTot));
    this.velocity.addScaledVector(this.gravityAcc, dt);
    this.frictionTot = 0;
  }

  updateRotation(dt: number): void {
    const len = this.angularVelocity.length();
    if (len < 1e-6) return;
    _spinAxis.copy(this.angularVelocity).divideScalar(len);
    _spinQuat.setFromAxisAngle(_spinAxis, len * dt);
    this.quaternion.multiplyQuaternions(_spinQuat, this.quaternion);
  }
}
