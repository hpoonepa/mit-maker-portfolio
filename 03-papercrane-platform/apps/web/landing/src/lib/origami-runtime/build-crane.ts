// Replays a playbook of fold commands (FOLD_REFLECTION, FOLD_REFLECTION_P,
// FOLD_ROTATION, FOLD_ROTATION_P, FOLD_CREASE) on a square paper, then bakes
// the final folded polygons into a triangulated THREE.BufferGeometry.

import * as THREE from "three";
import { OrigamiShape } from "./shape";
import { square } from "./paper-formats";
import { Polygon } from "./polygon";

type Cmd = {
  command: string;
  ppoint: number[];
  pnormal: number[];
  phi?: number;
  polygonIndex?: number;
};

function getPlane(cmd: Cmd): THREE.Plane {
  const normal = new THREE.Vector3().fromArray(cmd.pnormal);
  const coplanar = new THREE.Vector3().fromArray(cmd.ppoint);
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal.clone().normalize(), coplanar);
  // Stash raw (non-normalized) data — the runtime uses these for precision in
  // reflect/intersect math, mirroring the original reference implementation.
  (plane as unknown as { __raw: { normal: THREE.Vector3; coplanar: THREE.Vector3 } }).__raw = { normal, coplanar };
  return plane;
}

function runCommand(shape: OrigamiShape, cmd: Cmd): void {
  const plane = getPlane(cmd);
  switch (cmd.command) {
    case "FOLD_REFLECTION":
      shape.reflect(plane);
      break;
    case "FOLD_REFLECTION_P":
      if (cmd.polygonIndex !== undefined) shape.reflectIndex(plane, cmd.polygonIndex);
      break;
    case "FOLD_ROTATION":
      shape.fold(plane, cmd.phi ?? 0);
      break;
    case "FOLD_ROTATION_P":
      if (cmd.polygonIndex !== undefined) shape.foldIndex(plane, cmd.phi ?? 0, cmd.polygonIndex);
      break;
    case "FOLD_CREASE":
      shape.crease(plane);
      break;
  }
}

/**
 * Run the full playbook on a fresh square sheet, then triangulate the
 * resulting polygons into a single BufferGeometry.
 *
 * @param commands  Array of fold instructions (see crane.json).
 * @param targetRadius  Bounding-sphere radius after normalization. Use this
 *                      to fit the crane into your scene's scale.
 */
export function bakeOrigami(commands: Cmd[], targetRadius = 1.0): THREE.BufferGeometry {
  const shape = new OrigamiShape();
  shape.reset(square());

  for (const cmd of commands) runCommand(shape, cmd);

  shape.model.shrink();

  // Triangulate each polygon and build position/normal/uv buffers. UVs come
  // from each vertex's *unfolded* 2D coordinate on the paper sheet (origami
  // runtime tracks both 3D and 2D positions per vertex), normalized to [0,1].
  const positions: number[] = [];
  const normals: number[] = [];
  const uvs: number[] = [];
  const PAPER_SIZE = 400;

  const polygons = shape.model.getPolygons();
  for (const polyIndices of polygons) {
    if (polyIndices.length < 3) continue;
    const verts = polyIndices.map((idx) => shape.model.data.getVertex(idx));
    const verts2d = polyIndices.map((idx) => shape.model.data.getVertex2d(idx));
    const polygon = new Polygon(verts);
    if (!polygon.isStrictlyNonDegenerate()) continue;

    const tris = polygon.triangulate();
    if (!tris || tris.length === 0) continue;

    const normal = polygon.getNormal();

    for (const tri of tris as unknown as number[][]) {
      for (let k = 0; k < 3; k++) {
        const v = verts[tri[k]];
        const v2 = verts2d[tri[k]];
        positions.push(v.x, v.y, v.z);
        normals.push(normal.x, normal.y, normal.z);
        uvs.push(v2.x / PAPER_SIZE, v2.y / PAPER_SIZE);
      }
    }
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
  geom.setAttribute("normal", new THREE.BufferAttribute(new Float32Array(normals), 3));
  geom.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(uvs), 2));

  // Center on the bounding-box midpoint so the crane orbits around its own
  // visual center, not its (200, 200, *) origin.
  geom.computeBoundingBox();
  const bb = geom.boundingBox;
  if (bb) {
    const cx = (bb.max.x + bb.min.x) * 0.5;
    const cy = (bb.max.y + bb.min.y) * 0.5;
    const cz = (bb.max.z + bb.min.z) * 0.5;
    const pos = geom.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      pos.setXYZ(i, pos.getX(i) - cx, pos.getY(i) - cy, pos.getZ(i) - cz);
    }
    pos.needsUpdate = true;
  }

  // Normalize bounding sphere to the target radius for predictable scaling.
  geom.computeBoundingSphere();
  const r = geom.boundingSphere?.radius ?? 1;
  if (r > 0) geom.scale(targetRadius / r, targetRadius / r, targetRadius / r);

  geom.computeBoundingSphere();
  return geom;
}

/**
 * Fetch the crane playbook JSON and bake a folded crane geometry.
 * Cached, so multiple callers share the same Promise.
 */
let cachedPromise: Promise<THREE.BufferGeometry> | null = null;
export function getCraneGeometry(targetRadius = 0.4): Promise<THREE.BufferGeometry> {
  if (cachedPromise) return cachedPromise;
  cachedPromise = fetch("/_landing/origami/crane.json")
    .then((r) => r.json())
    .then((commands: Cmd[]) => bakeOrigami(commands, targetRadius));
  return cachedPromise;
}
