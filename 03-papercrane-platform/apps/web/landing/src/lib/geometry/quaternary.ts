import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { createHelixGeometry } from "./helix";
import { createBetaSheetGeometry } from "./beta-sheet";

/**
 * A small "quaternary assembly" — two short α-helices flanking a central β-sheet,
 * suggesting a protein subunit interface. Merged to a single static geometry for
 * instanced rendering.
 */
export function createQuaternaryGeometry(): THREE.BufferGeometry {
  const helixA = createHelixGeometry({
    turns: 2.6,
    helixRadius: 0.32,
    height: 1.05,
    tubeRadius: 0.115,
    pathSegments: 128,
    radialSegments: 14,
  });
  helixA.translate(0.42, 0, 0);

  const helixB = createHelixGeometry({
    turns: 2.6,
    helixRadius: 0.32,
    height: 1.05,
    tubeRadius: 0.115,
    pathSegments: 128,
    radialSegments: 14,
  });
  helixB.rotateY(Math.PI);
  helixB.translate(-0.42, 0.05, 0);

  const sheet = createBetaSheetGeometry({
    width: 0.42,
    bodyLength: 0.85,
    arrowExtra: 0.22,
    arrowOverhang: 0.13,
    thickness: 0.12,
    bevel: 0.03,
  });
  sheet.rotateZ(Math.PI / 2);
  sheet.translate(0, -0.02, 0.18);

  // mergeGeometries requires all parts share index/attribute layout. The two
  // tube helices are indexed; the extruded sheet is not — flatten everything
  // to non-indexed before merging.
  const parts = [helixA, helixB, sheet].map((g) => {
    g.deleteAttribute("uv");
    return g.index ? g.toNonIndexed() : g;
  });
  const merged = mergeGeometries(parts);
  helixA.dispose();
  helixB.dispose();
  sheet.dispose();
  for (const p of parts) p.dispose();
  if (!merged) throw new Error("quaternary merge failed");
  merged.computeBoundingSphere();
  merged.computeVertexNormals();
  return merged;
}
