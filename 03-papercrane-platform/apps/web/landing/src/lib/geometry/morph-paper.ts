import * as THREE from "three";
import { getSeedRandomFn } from "../math/seed-random";

/**
 * Build a flat paper sheet with a "crane" morph target. The sheet is a
 * subdivided plane (so we have enough vertices for a folded silhouette);
 * its `morphAttributes.position[0]` array holds the absolute target positions
 * approximating an origami crane.
 *
 * The base mesh is given perimeter jaggedness + a gentle curl to read as
 * paper at rest. The morph target is the same vertex count, repositioned
 * via fold rules: tent crease along x=0, head/tail elongation in y, and
 * wing-tip dip on the outer-x edges.
 */
export function createMorphPaperGeometry(
  opts: {
    width?: number;
    height?: number;
    segX?: number;
    segY?: number;
    jaggedness?: number;
    curlAmount?: number;
    seed?: string;
  } = {},
): THREE.BufferGeometry {
  const width = opts.width ?? 1.15;
  const height = opts.height ?? 0.78;
  const segX = opts.segX ?? 10;
  const segY = opts.segY ?? 8;
  const jaggedness = opts.jaggedness ?? 0.05;
  const curlAmount = opts.curlAmount ?? 0.06;
  const seed = opts.seed ?? "morph-paper";

  const geom = new THREE.PlaneGeometry(width, height, segX, segY);
  const rand = getSeedRandomFn(seed);
  const halfW = width / 2;
  const halfH = height / 2;

  // Jaggedness on perimeter + gentle curl on z, both applied to base positions.
  const pos = geom.attributes.position;
  const base = pos.array as Float32Array;
  for (let i = 0; i < base.length; i += 3) {
    const x = base[i];
    const y = base[i + 1];
    const onLeft = Math.abs(x + halfW) < 1e-4;
    const onRight = Math.abs(x - halfW) < 1e-4;
    const onTop = Math.abs(y - halfH) < 1e-4;
    const onBot = Math.abs(y + halfH) < 1e-4;
    if (onTop || onBot) base[i + 1] += (rand() - 0.5) * jaggedness;
    if (onLeft || onRight) base[i] += (rand() - 0.5) * jaggedness;
  }
  for (let i = 0; i < base.length; i += 3) {
    const x = base[i];
    const norm = x / halfW;
    base[i + 2] += curlAmount * (1 - norm * norm);
  }
  pos.needsUpdate = true;

  // Crane target positions — exaggerated so the fold reads at a glance.
  // Geometry: a vertical body crease (huge +z peak), elongated head (top y)
  // tilted forward+up, swept-down wings (large |x|), and a long tail (bottom y).
  const crane = new Float32Array(base.length);
  for (let i = 0; i < base.length; i += 3) {
    const x = base[i];
    const y = base[i + 1];

    const xn = x / halfW; // -1..1
    const yn = y / halfH; // -1..1
    const xAbs = Math.abs(xn);
    const yAbs = Math.abs(yn);

    // Body crease — sharp peak along x=0, falling to z=-0.2 at outer x (wing dip).
    let cz = (1 - xAbs) * 1.1 - xAbs * 0.35;

    // Width pinch: pull mid-x toward the centerline (folded body is narrower).
    let cx = xn * (0.55 + 0.45 * xAbs) * halfW;

    let cy = y;

    // Head: top portion elongates upward and tilts forward (+z bias).
    if (yn > 0.25) {
      const t = (yn - 0.25) / 0.75; // 0..1
      cy = halfH * (0.25 + (yn - 0.25) * 1.6);
      cz += t * 0.55; // head/beak rises
      cx *= 1 - t * 0.4; // beak narrows toward midline
    }

    // Tail: lower portion elongates downward and tilts back (-z bias).
    if (yn < -0.25) {
      const t = (-yn - 0.25) / 0.75;
      cy = -halfH * (0.25 + (-yn - 0.25) * 1.5);
      cz -= t * 0.4;
      cx *= 1 - t * 0.5; // tail narrows
    }

    // Wings: outer-x panels fold sharply down and forward (+y).
    if (xAbs > 0.4 && yAbs < 0.6) {
      const t = (xAbs - 0.4) / 0.6;
      cz -= t * 0.6;
      cy += t * 0.18; // wings sweep slightly forward
    }

    crane[i] = cx;
    crane[i + 1] = cy;
    crane[i + 2] = cz;
  }

  geom.morphAttributes.position = [
    new THREE.Float32BufferAttribute(crane, 3),
  ];
  // Optional: morph normals computed lazily by Three.js when influence > 0.
  geom.computeVertexNormals();
  geom.computeBoundingSphere();

  return geom;
}
