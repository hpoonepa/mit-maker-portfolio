import * as THREE from "three";
import { getSeedRandomFn } from "../math/seed-random";

/**
 * Flat paper-like rectangle with irregular torn edges. Built as a Shape with
 * jittered perimeter points and shallow extrude for slight thickness.
 */
export function createTornPaperGeometry(
  opts: {
    width?: number;
    height?: number;
    jaggedness?: number;
    perimeterPoints?: number;
    thickness?: number;
    seed?: string;
    /** Max bend along x-axis (sheet curl). 0 = perfectly flat. */
    curlAmount?: number;
    /** Direction of dominant curl: "x" bows around y-axis, "y" bows around x-axis. */
    curlAxis?: "x" | "y";
  } = {},
): THREE.BufferGeometry {
  const width = opts.width ?? 1.0;
  const height = opts.height ?? 0.7;
  const jaggedness = opts.jaggedness ?? 0.06;
  const perSide = Math.max(8, Math.floor((opts.perimeterPoints ?? 56) / 4));
  const thickness = opts.thickness ?? 0.05;
  const curlAmount = opts.curlAmount ?? 0.08;
  const curlAxis = opts.curlAxis ?? "x";
  const rand = getSeedRandomFn(opts.seed ?? "paper-default");

  const halfW = width / 2;
  const halfH = height / 2;

  const pts: Array<[number, number]> = [];

  // Top edge (left -> right)
  for (let i = 0; i <= perSide; i++) {
    const t = i / perSide;
    pts.push([
      -halfW + t * width + (i === 0 || i === perSide ? 0 : (rand() - 0.5) * jaggedness * 0.5),
      halfH + (i === 0 || i === perSide ? 0 : (rand() - 0.5) * jaggedness),
    ]);
  }
  // Right edge (top -> bottom), skip first (corner already added)
  for (let i = 1; i <= perSide; i++) {
    const t = i / perSide;
    pts.push([
      halfW + (i === perSide ? 0 : (rand() - 0.5) * jaggedness),
      halfH - t * height + (i === perSide ? 0 : (rand() - 0.5) * jaggedness * 0.5),
    ]);
  }
  // Bottom edge (right -> left)
  for (let i = 1; i <= perSide; i++) {
    const t = i / perSide;
    pts.push([
      halfW - t * width + (i === perSide ? 0 : (rand() - 0.5) * jaggedness * 0.5),
      -halfH + (i === perSide ? 0 : (rand() - 0.5) * jaggedness),
    ]);
  }
  // Left edge (bottom -> top), skip last (closes back to start)
  for (let i = 1; i < perSide; i++) {
    const t = i / perSide;
    pts.push([
      -halfW + (rand() - 0.5) * jaggedness,
      -halfH + t * height + (rand() - 0.5) * jaggedness * 0.5,
    ]);
  }

  const shape = new THREE.Shape();
  shape.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i][0], pts[i][1]);
  shape.closePath();

  const geom = new THREE.ExtrudeGeometry(shape, {
    depth: thickness,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelThickness: thickness * 0.25,
    bevelSize: thickness * 0.25,
    steps: 1,
    curveSegments: 1,
  });
  geom.translate(0, 0, -thickness / 2);

  // Curl: parabolic bow so the sheet reads as paper, not card-stock.
  if (curlAmount > 0) {
    const halfW = width / 2;
    const halfH = height / 2;
    const positions = geom.attributes.position;
    const arr = positions.array as Float32Array;
    for (let i = 0; i < arr.length; i += 3) {
      const x = arr[i];
      const y = arr[i + 1];
      const norm = curlAxis === "x" ? x / halfW : y / halfH;
      // Concave parabola peaks at center; subtract for inverted bow.
      arr[i + 2] += curlAmount * (1 - norm * norm);
    }
    positions.needsUpdate = true;
    geom.computeVertexNormals();
  }

  geom.computeBoundingSphere();
  return geom;
}
