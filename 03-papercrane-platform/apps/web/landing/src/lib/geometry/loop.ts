import * as THREE from "three";
import { getSeedRandomFn } from "../math/seed-random";

/**
 * Random curved "loop" — short connecting coil between secondary structure
 * elements in a protein cartoon. Built as a Catmull-Rom tube with seeded
 * random control points so each variant looks different but reproducible.
 */
export function createLoopGeometry(
  opts: {
    seed?: string;
    span?: number;
    waviness?: number;
    tubeRadius?: number;
    pathSegments?: number;
    radialSegments?: number;
  } = {},
): THREE.BufferGeometry {
  const seed = opts.seed ?? "loop-default";
  const span = opts.span ?? 1.1;
  const waviness = opts.waviness ?? 0.55;
  const tubeRadius = opts.tubeRadius ?? 0.11;
  const pathSegments = opts.pathSegments ?? 140;
  const radialSegments = opts.radialSegments ?? 18;

  const rand = getSeedRandomFn(seed);
  const half = span / 2;
  // 5 control points: anchored at -span/2 and +span/2, three wandering interior.
  const pts = [
    new THREE.Vector3(0, -half, 0),
    new THREE.Vector3((rand() - 0.5) * waviness, -half * 0.5, (rand() - 0.5) * waviness),
    new THREE.Vector3((rand() - 0.5) * waviness, 0, (rand() - 0.5) * waviness),
    new THREE.Vector3((rand() - 0.5) * waviness, half * 0.5, (rand() - 0.5) * waviness),
    new THREE.Vector3(0, half, 0),
  ];
  const curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.5);
  const geom = new THREE.TubeGeometry(curve, pathSegments, tubeRadius, radialSegments, false);
  geom.deleteAttribute("uv");
  geom.computeBoundingSphere();
  return geom;
}
