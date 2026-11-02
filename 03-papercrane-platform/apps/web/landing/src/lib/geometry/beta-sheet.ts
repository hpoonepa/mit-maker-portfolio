import * as THREE from "three";

/**
 * Beta sheet — a flat extruded arrow with bevelled edges. Visual analogue of a
 * β-strand in a protein cartoon diagram (broad arrow pointing toward the C-terminus).
 */
export function createBetaSheetGeometry(
  opts: {
    width?: number;
    bodyLength?: number;
    arrowExtra?: number;
    arrowOverhang?: number;
    thickness?: number;
    bevel?: number;
  } = {},
): THREE.BufferGeometry {
  const width = opts.width ?? 0.46;
  const bodyLength = opts.bodyLength ?? 0.95;
  const arrowExtra = opts.arrowExtra ?? 0.26;
  const arrowOverhang = opts.arrowOverhang ?? 0.16;
  const thickness = opts.thickness ?? 0.13;
  // Larger bevel + more bevel segments = AlphaFold-style soft ribbon edges.
  const bevel = opts.bevel ?? 0.042;

  const halfW = width / 2;
  const arrowHalfW = halfW + arrowOverhang;
  const totalLen = bodyLength + arrowExtra;
  const halfLen = totalLen / 2;
  const bodyTop = halfLen - arrowExtra;

  const shape = new THREE.Shape();
  shape.moveTo(-halfW, -halfLen);
  shape.lineTo(halfW, -halfLen);
  shape.lineTo(halfW, bodyTop);
  shape.lineTo(arrowHalfW, bodyTop);
  shape.lineTo(0, halfLen);
  shape.lineTo(-arrowHalfW, bodyTop);
  shape.lineTo(-halfW, bodyTop);
  shape.closePath();

  const geom = new THREE.ExtrudeGeometry(shape, {
    depth: thickness,
    bevelEnabled: true,
    bevelSegments: 10,
    bevelThickness: bevel,
    bevelSize: bevel,
    steps: 1,
    curveSegments: 24,
  });
  // Center on z so the sheet body sits about its origin.
  geom.translate(0, 0, -thickness / 2 - bevel / 2);
  geom.deleteAttribute("uv");
  geom.computeBoundingSphere();
  return geom;
}
