import * as THREE from "three";

/**
 * Tiny flying-bird silhouette: two swept-back wing triangles joined along a
 * short body spine. Wing tips dip slightly for a gull / paper-crane-in-flight
 * read. Lies roughly in the xz plane with -y as the wing-dip direction.
 *
 * Returned geometry is normalized so its bounding-sphere radius matches
 * `targetRadius`.
 */
export function createBirdGeometry(targetRadius = 0.18): THREE.BufferGeometry {
  // Local design coordinates (will be normalized at the end).
  const wingHalfSpan = 0.6;
  const wingDip = 0.12;
  const wingSweepBack = 0.35;
  const headZ = 0.32;
  const tailZ = -0.18;

  // Body spine offset (avoid degenerate triangles at the centerline).
  const spine = 0.04;

  // 6 vertices: head, tail, two body-spine points, two wing tips.
  const verts = new Float32Array([
    // 0: head (front)
    0, 0, headZ,
    // 1: tail (back)
    0, 0, tailZ,
    // 2: left body shoulder
    -spine, 0, 0,
    // 3: right body shoulder
    spine, 0, 0,
    // 4: left wing tip
    -wingHalfSpan, -wingDip, -wingSweepBack,
    // 5: right wing tip
    wingHalfSpan, -wingDip, -wingSweepBack,
  ]);

  const indices = [
    // Left wing: head → left shoulder → left tip → tail
    0, 2, 4,
    2, 1, 4,
    // Right wing: head → right tip → right shoulder → tail
    0, 5, 3,
    3, 5, 1,
  ];

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(verts, 3));
  geom.setIndex(indices);
  geom.computeVertexNormals();

  // Normalize so its bounding sphere has radius targetRadius.
  geom.computeBoundingSphere();
  const r = geom.boundingSphere?.radius ?? 1;
  geom.scale(targetRadius / r, targetRadius / r, targetRadius / r);
  geom.computeBoundingSphere();
  geom.computeVertexNormals();
  return geom;
}
