// Subset of georgiee/origami's shared/math.ts — only what's needed for the
// fold-replay pipeline (no camera projection helpers).

import * as THREE from "three";

export function pointOnPlane(plane: THREE.Plane, point: THREE.Vector3, threshold = 1): boolean {
  return Math.abs(plane.distanceToPoint(point)) < threshold;
}

export function planeBetweenPoints3(plane: THREE.Plane, v1: THREE.Vector3, v2: THREE.Vector3): boolean {
  const distance1 = plane.distanceToPoint(v1);
  const distance2 = plane.distanceToPoint(v2);
  let inner = false;
  let outer = false;
  if (distance1 > 0.00000001) inner = true;
  if (distance1 < -0.00000001) outer = true;
  if (distance2 > 0.00000001) inner = true;
  if (distance2 < -0.00000001) outer = true;
  return inner && outer;
}

export function polygonContains(point: [number, number], vs: [number, number][]): boolean {
  const x = point[0];
  const y = point[1];
  let inside = false;
  for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
    const xi = vs[i][0];
    const yi = vs[i][1];
    const xj = vs[j][0];
    const yj = vs[j][1];
    const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}
