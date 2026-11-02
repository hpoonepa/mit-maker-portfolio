import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * Procedural origami crane built from triangular paper panels parented into a
 * group hierarchy. Each panel pivots around its hinge edge. Animating the panel
 * rotations from flat (all-0) to "rest" forms a recognizable origami crane.
 */
export type CranePart = {
  name: string;
  mesh: THREE.Mesh;
  pivot: THREE.Group; // applies the hinge rotation
  hingeAxis: THREE.Vector3; // local axis to rotate around
  restAngle: number; // radians at fold completion
  startTime: number; // 0..1 normalized along the fold timeline
  endTime: number; // 0..1
};

export type Crane = {
  root: THREE.Group;
  parts: CranePart[];
};

const PAPER = "#fbf6ec";

function makePanel(geom: THREE.BufferGeometry, mat: THREE.Material): THREE.Mesh {
  const m = new THREE.Mesh(geom, mat);
  m.castShadow = false;
  m.receiveShadow = false;
  return m;
}

function triangle(...pts: [number, number, number][]): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  const flat = new Float32Array(pts.flat());
  g.setAttribute("position", new THREE.BufferAttribute(flat, 3));
  g.setIndex([0, 1, 2]);
  g.computeVertexNormals();
  return g;
}

function quad(
  a: [number, number, number],
  b: [number, number, number],
  c: [number, number, number],
  d: [number, number, number],
): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  const flat = new Float32Array([...a, ...b, ...c, ...d]);
  g.setAttribute("position", new THREE.BufferAttribute(flat, 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.computeVertexNormals();
  return g;
}

/**
 * Build a paper-crane assembly. The crane sits with its long body axis along
 * +y; the head points along +x, the tail along -x. Wings pivot around the body
 * spine (z-axis at x=0).
 *
 * The "flat" state is all panels coplanar in the xz plane (y=0).
 * The "folded" state has each panel rotated to its restAngle.
 */
export function buildCrane(): Crane {
  const mat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(PAPER),
    roughness: 0.78,
    metalness: 0,
    side: THREE.DoubleSide,
    envMapIntensity: 0.55,
    flatShading: true,
  });

  const root = new THREE.Group();
  root.name = "crane";

  // ---- Body spine (the "kite" body) ---------------------------------------
  // Two vertical triangles back-to-back forming a fin along the y axis.
  const bodyHeight = 1.4;
  const bodyHalfDepth = 0.55;
  const bodyHalfWidthBack = 0.35;
  const bodyPivot = new THREE.Group();
  bodyPivot.position.set(0, 0, 0);
  // Body geom: kite shape in YZ plane (x=0)
  const bodyGeom = quad(
    [0, -bodyHeight * 0.5, -bodyHalfDepth], // bottom-back
    [0, -bodyHeight * 0.5, bodyHalfDepth], // bottom-front
    [0, bodyHeight * 0.5, bodyHalfWidthBack], // top-front
    [0, bodyHeight * 0.5, -bodyHalfWidthBack], // top-back
  );
  const body = makePanel(bodyGeom, mat);
  bodyPivot.add(body);
  root.add(bodyPivot);

  // ---- Wings --------------------------------------------------------------
  // Wing pivot at top of body spine (y=+0.4). Hinges around y axis (sweeping
  // outward from spine). In "flat" the wing lies in y=0 plane (rotated 90°
  // around z). In "folded" it sweeps -65° (left) or +65° (right) around z to
  // form the swept-down wing of a crane.
  const wingLength = 1.4;
  const wingChord = 0.95;
  const wingY = bodyHeight * 0.18; // hinge height on body
  const wingGeom = (sign: 1 | -1) =>
    triangle(
      [0, 0, 0], // root (at hinge)
      [sign * wingLength, 0.05 * sign, -wingChord * 0.55], // tip back
      [sign * wingLength * 0.92, -0.18, wingChord * 0.45], // tip front-down
    );

  const leftPivot = new THREE.Group();
  leftPivot.position.set(0, wingY, 0);
  const leftWing = makePanel(wingGeom(-1), mat);
  leftPivot.add(leftWing);
  root.add(leftPivot);

  const rightPivot = new THREE.Group();
  rightPivot.position.set(0, wingY, 0);
  const rightWing = makePanel(wingGeom(1), mat);
  rightPivot.add(rightWing);
  root.add(rightPivot);

  // ---- Head/neck ----------------------------------------------------------
  // Pivot at body top, hinges along z so the neck rises forward.
  const headPivot = new THREE.Group();
  headPivot.position.set(0, bodyHeight * 0.5, 0);
  const headGeom = triangle(
    [0, 0, 0],
    [0, 0.55, -0.18],
    [0, 0.45, 0.18],
  );
  const head = makePanel(headGeom, mat);
  headPivot.add(head);
  root.add(headPivot);

  // ---- Beak ---------------------------------------------------------------
  // Pivots at head tip, swings down to form a beak.
  const beakPivot = new THREE.Group();
  beakPivot.position.set(0, bodyHeight * 0.5 + 0.5, 0); // approximate head tip
  const beakGeom = triangle(
    [0, 0, 0],
    [0, -0.16, 0.32],
    [0, -0.04, 0.08],
  );
  const beak = makePanel(beakGeom, mat);
  beakPivot.add(beak);
  root.add(beakPivot);

  // ---- Tail ---------------------------------------------------------------
  // Pivots at body base, swings back to form a tail spike.
  const tailPivot = new THREE.Group();
  tailPivot.position.set(0, -bodyHeight * 0.5, 0);
  const tailGeom = triangle(
    [0, 0, 0],
    [0, -0.55, -0.5],
    [0, -0.35, -0.15],
  );
  const tail = makePanel(tailGeom, mat);
  tailPivot.add(tail);
  root.add(tailPivot);

  // Initial (flat) rotations: collapse the 3D crane into a flat sheet.
  // We achieve "flat" by setting each pivot's rotation to its FLAT angle
  // (often -restAngle if rest is the folded state). To keep authoring simple
  // we record rest angles + start with the inverse so geometry begins flat.
  const parts: CranePart[] = [
    {
      name: "body",
      mesh: body,
      pivot: bodyPivot,
      hingeAxis: new THREE.Vector3(0, 1, 0),
      restAngle: 0, // body is upright in rest; we tilt the wing/head etc instead
      startTime: 0,
      endTime: 0.05,
    },
    {
      name: "leftWing",
      mesh: leftWing,
      pivot: leftPivot,
      hingeAxis: new THREE.Vector3(0, 0, 1),
      restAngle: -1.05, // ~-60°: sweeps wing down/out
      startTime: 0.35,
      endTime: 0.7,
    },
    {
      name: "rightWing",
      mesh: rightWing,
      pivot: rightPivot,
      hingeAxis: new THREE.Vector3(0, 0, 1),
      restAngle: 1.05,
      startTime: 0.35,
      endTime: 0.7,
    },
    {
      name: "head",
      mesh: head,
      pivot: headPivot,
      hingeAxis: new THREE.Vector3(0, 0, 1),
      restAngle: -1.1, // tilt head forward over the body
      startTime: 0.6,
      endTime: 0.85,
    },
    {
      name: "beak",
      mesh: beak,
      pivot: beakPivot,
      hingeAxis: new THREE.Vector3(0, 0, 1),
      restAngle: 0.9,
      startTime: 0.78,
      endTime: 0.95,
    },
    {
      name: "tail",
      mesh: tail,
      pivot: tailPivot,
      hingeAxis: new THREE.Vector3(0, 0, 1),
      restAngle: 0.9,
      startTime: 0.5,
      endTime: 0.78,
    },
  ];

  // Set everything to flat initially.
  for (const p of parts) {
    p.pivot.rotation.set(0, 0, 0);
  }

  return { root, parts };
}

function smoothstep(t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return t * t * (3 - 2 * t);
}

/**
 * Bake the fully-folded origami crane into a single static BufferGeometry.
 * Each panel's pivot transform is applied to its vertices, then all panels
 * merge into one geometry. Result is normalized so its bounding sphere has
 * radius `targetRadius` for predictable cluster sizing.
 */
export function createFoldedCraneGeometry(
  targetRadius = 1.0,
): THREE.BufferGeometry {
  const crane = buildCrane();
  setCraneProgress(crane, 1.0);
  crane.root.updateMatrixWorld(true);

  const parts: THREE.BufferGeometry[] = [];
  crane.root.traverse((obj) => {
    if (obj instanceof THREE.Mesh) {
      const baked = obj.geometry.clone();
      baked.applyMatrix4(obj.matrixWorld);
      // Strip non-position attributes so all parts share a uniform layout
      // (mergeGeometries requires this).
      for (const name of Object.keys(baked.attributes)) {
        if (name !== "position") baked.deleteAttribute(name);
      }
      baked.deleteAttribute("uv");
      parts.push(baked);
    }
  });

  const merged = mergeGeometries(parts);
  for (const g of parts) g.dispose();
  if (!merged) throw new Error("crane merge failed");

  // Normalize to target bounding sphere.
  merged.computeBoundingSphere();
  const r = merged.boundingSphere?.radius ?? 1;
  merged.scale(targetRadius / r, targetRadius / r, targetRadius / r);
  merged.computeBoundingSphere();
  merged.computeVertexNormals();
  return merged;
}

/**
 * Drive the crane to a normalized fold progress in [0, 1].
 * 0 = flat sheet, 1 = fully folded crane.
 */
export function setCraneProgress(crane: Crane, progress: number): void {
  for (const p of crane.parts) {
    const span = Math.max(0.0001, p.endTime - p.startTime);
    const local = smoothstep((progress - p.startTime) / span);
    const angle = local * p.restAngle;
    if (Math.abs(p.hingeAxis.x) > 0.5) p.pivot.rotation.x = angle;
    else if (Math.abs(p.hingeAxis.y) > 0.5) p.pivot.rotation.y = angle;
    else p.pivot.rotation.z = angle;
  }
}
