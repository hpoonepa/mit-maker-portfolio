import * as THREE from "three";

class HelixCurve extends THREE.Curve<THREE.Vector3> {
  constructor(
    public turns: number,
    public radius: number,
    public height: number,
  ) {
    super();
  }
  override getPoint(t: number, target = new THREE.Vector3()): THREE.Vector3 {
    const angle = t * this.turns * Math.PI * 2;
    return target.set(
      Math.cos(angle) * this.radius,
      (t - 0.5) * this.height,
      Math.sin(angle) * this.radius,
    );
  }
}

/** α-helix as a smooth circular tube swept along a helical curve. */
export function createHelixGeometry(
  opts: {
    turns?: number;
    helixRadius?: number;
    height?: number;
    tubeRadius?: number;
    pathSegments?: number;
    radialSegments?: number;
  } = {},
): THREE.BufferGeometry {
  const turns = opts.turns ?? 3;
  const helixRadius = opts.helixRadius ?? 0.34;
  const height = opts.height ?? 1.1;
  const tubeRadius = opts.tubeRadius ?? 0.13;
  const pathSegments = opts.pathSegments ?? 240;
  const radialSegments = opts.radialSegments ?? 22;

  const curve = new HelixCurve(turns, helixRadius, height);
  const geom = new THREE.TubeGeometry(curve, pathSegments, tubeRadius, radialSegments, false);
  geom.deleteAttribute("uv");
  geom.computeBoundingSphere();
  return geom;
}
