import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * Lusion-style "jack": three perpendicular hollow cylinders with bevelled
 * (filleted) rims at every open end. The visible rim transition from outer
 * wall to inner bore is a smooth quarter-arc, so it reads as soft plastic
 * rather than a razor-sharp 90° corner.
 *
 * The three-cylinder intersection at the center is left as raw overlap (this
 * matches the reference image — small visible seam where surfaces meet).
 */
export function createJackGeometry(
  opts: { radius?: number; length?: number; segments?: number } = {},
): THREE.BufferGeometry {
  const radius = opts.radius ?? 0.3;
  const length = opts.length ?? 1.25;
  const segments = opts.segments ?? 64;
  const innerRadius = radius * 0.5;
  const wallThickness = radius - innerRadius;
  const fillet = wallThickness * 0.55; // bevel arc radius — wider, softer rim
  const filletSegs = 12;

  function makeAxisCylinder(rotateAxis: "x" | "y" | "z"): THREE.BufferGeometry {
    // Outer wall, shortened on each end so the fillet arc fits.
    const outer = new THREE.CylinderGeometry(
      radius,
      radius,
      length - 2 * fillet,
      segments,
      1,
      true,
    );
    stripUv(outer);

    // Inner bore wall, also shortened. Indices flipped so the surface faces
    // inward (we look down the bore from the outside; back wall lights as a
    // shaded interior).
    const inner = new THREE.CylinderGeometry(
      innerRadius,
      innerRadius,
      length - 2 * fillet,
      segments,
      1,
      true,
    );
    flipIndex(inner);
    inner.computeVertexNormals();
    stripUv(inner);

    const filletTop = makeFilletRing(
      innerRadius,
      radius,
      fillet,
      length / 2 - fillet,
      1,
      segments,
      filletSegs,
    );
    const filletBot = makeFilletRing(
      innerRadius,
      radius,
      fillet,
      -length / 2 + fillet,
      -1,
      segments,
      filletSegs,
    );

    const merged = mergeGeometries([outer, inner, filletTop, filletBot]);
    outer.dispose();
    inner.dispose();
    filletTop.dispose();
    filletBot.dispose();
    if (!merged) throw new Error("merge failed (axis cylinder)");
    if (rotateAxis === "x") merged.rotateZ(Math.PI / 2);
    else if (rotateAxis === "z") merged.rotateX(Math.PI / 2);
    return merged;
  }

  const parts = [makeAxisCylinder("y"), makeAxisCylinder("x"), makeAxisCylinder("z")];
  const merged = mergeGeometries(parts);
  for (const p of parts) p.dispose();
  if (!merged) throw new Error("merge failed (jack)");
  merged.computeBoundingSphere();
  return merged;
}

function stripUv(geom: THREE.BufferGeometry): void {
  geom.deleteAttribute("uv");
}

function flipIndex(geom: THREE.BufferGeometry): void {
  const idx = geom.getIndex();
  if (!idx) return;
  const arr = idx.array as Uint16Array | Uint32Array;
  for (let i = 0; i < arr.length; i += 3) {
    const t = arr[i + 1];
    arr[i + 1] = arr[i + 2];
    arr[i + 2] = t;
  }
  idx.needsUpdate = true;
}

/**
 * Lathe-build a quarter-torus surface joining the outer cylinder wall to the
 * inner bore at one end of the tube.
 *
 * Profile (in radial-axial 2D coords) is a quarter circle of radius `fillet`
 * centered at (outerR - fillet, yEnd), going from angle 0 (at the outer wall)
 * to π/2 (at the inner bore lip), then a flat radial segment from the lip to
 * the inner bore radius. Rotated around the cylinder axis to produce a 3D
 * mesh.
 */
function makeFilletRing(
  innerR: number,
  outerR: number,
  fillet: number,
  yEnd: number,
  sign: 1 | -1,
  segs: number,
  arcSegs: number,
): THREE.BufferGeometry {
  // Build profile: quarter-arc bevel from outer wall to rim plane, then flat
  // ring from rim outer to inner bore.
  const cx = outerR - fillet;
  const profile: { r: number; y: number }[] = [];
  for (let i = 0; i <= arcSegs; i++) {
    const t = i / arcSegs;
    const angle = (t * Math.PI) / 2;
    profile.push({
      r: cx + Math.cos(angle) * fillet,
      y: yEnd + sign * Math.sin(angle) * fillet,
    });
  }
  // The bevel ends at r = cx, y = yEnd + sign*fillet (which is the rim plane).
  const rimY = yEnd + sign * fillet;
  // Flat radial segment: from (cx, rimY) inward to (innerR, rimY).
  profile.push({ r: innerR, y: rimY });

  const verts: number[] = [];
  const indices: number[] = [];
  for (let s = 0; s <= segs; s++) {
    const phi = (s / segs) * Math.PI * 2;
    const cs = Math.cos(phi);
    const sn = Math.sin(phi);
    for (const p of profile) verts.push(p.r * cs, p.y, p.r * sn);
  }
  const profLen = profile.length;
  for (let s = 0; s < segs; s++) {
    for (let p = 0; p < profLen - 1; p++) {
      const a = s * profLen + p;
      const b = (s + 1) * profLen + p;
      const c = (s + 1) * profLen + p + 1;
      const d = s * profLen + p + 1;
      if (sign > 0) {
        indices.push(a, b, c);
        indices.push(a, c, d);
      } else {
        indices.push(a, c, b);
        indices.push(a, d, c);
      }
    }
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute(
    "position",
    new THREE.BufferAttribute(new Float32Array(verts), 3),
  );
  geom.setIndex(indices);
  geom.computeVertexNormals();
  return geom;
}
