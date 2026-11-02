import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * "Ligand" — small bonded triplet of spheres (like a tiny molecule/cofactor in
 * a protein cartoon scene). Three atoms in a triangle, joined visually by
 * thin connector cylinders.
 */
export function createLigandGeometry(
  opts: { atomRadius?: number; bondLength?: number; sphereSegments?: number } = {},
): THREE.BufferGeometry {
  const atomRadius = opts.atomRadius ?? 0.22;
  const bondLength = opts.bondLength ?? 0.3;
  const segs = opts.sphereSegments ?? 28;

  const half = bondLength / 2;
  const apex = bondLength * Math.sqrt(3) / 2;

  const a1 = new THREE.SphereGeometry(atomRadius, segs, segs);
  a1.translate(-half, -apex / 3, 0);
  const a2 = new THREE.SphereGeometry(atomRadius, segs, segs);
  a2.translate(half, -apex / 3, 0);
  const a3 = new THREE.SphereGeometry(atomRadius * 0.85, segs, segs);
  a3.translate(0, (apex * 2) / 3, 0);

  const bondR = atomRadius * 0.32;
  const bondSegs = 18;
  // Bond a1–a2 (horizontal)
  const b12 = new THREE.CylinderGeometry(bondR, bondR, bondLength, bondSegs);
  b12.rotateZ(Math.PI / 2);
  b12.translate(0, -apex / 3, 0);
  // Bond a1–a3 (left-up)
  const len13 = Math.hypot(half, apex);
  const b13 = new THREE.CylinderGeometry(bondR, bondR, len13, bondSegs);
  const angle13 = Math.atan2(apex, -half) - Math.PI / 2;
  b13.rotateZ(angle13);
  b13.translate(-half / 2, apex / 6, 0);
  // Bond a2–a3 (right-up)
  const b23 = new THREE.CylinderGeometry(bondR, bondR, len13, bondSegs);
  const angle23 = Math.atan2(apex, half) - Math.PI / 2;
  b23.rotateZ(angle23);
  b23.translate(half / 2, apex / 6, 0);

  const parts = [a1, a2, a3, b12, b13, b23].map((g) => {
    g.deleteAttribute("uv");
    return g;
  });
  const merged = mergeGeometries(parts);
  for (const p of parts) p.dispose();
  if (!merged) throw new Error("ligand merge failed");
  merged.computeBoundingSphere();
  merged.computeVertexNormals();
  return merged;
}
