// Ported from georgiee/origami: src/origami/core/paper-formats.ts

import * as THREE from "three";
import { OrigamiModel } from "./model";
import { OrigamiGeometryData } from "./geometry-data";

export function square(): OrigamiModel {
  const data = new OrigamiGeometryData();

  data.addVertex(new THREE.Vector3(0, 0, 0));
  data.addVertex(new THREE.Vector3(400, 0, 0));
  data.addVertex(new THREE.Vector3(400, 400, 0));
  data.addVertex(new THREE.Vector3(0, 400, 0));

  data.addVertex2d(new THREE.Vector3(0, 0, 0));
  data.addVertex2d(new THREE.Vector3(400, 0, 0));
  data.addVertex2d(new THREE.Vector3(400, 400, 0));
  data.addVertex2d(new THREE.Vector3(0, 400, 0));

  data.addPolygon([0, 1, 2, 3]);

  return new OrigamiModel(data);
}
