// Ported from georgiee/origami: src/origami/shape.ts (cleaned: no window
// listener / debug logs; updated to current three.js plane API).

import * as THREE from "three";
import { OrigamiModel } from "./model";
import * as plainMath from "./plain-math";
import { Polygon } from "./polygon";

const VERTEX_POSITION = {
  COPLANAR: 0,
  FRONT: 1,
  BACK: 2,
};

type CutNode = { v1: number; v2: number; result: number | { added: number } };

export class OrigamiShape {
  public model: OrigamiModel;
  private cutpolygonNodes: CutNode[] = [];
  private cutpolygonPairs: number[][] = [];
  private lastCutPolygons: number[][] = [];

  constructor() {
    this.model = new OrigamiModel();
  }

  public resetCutHistory(): void {
    this.cutpolygonNodes = [];
    this.cutpolygonPairs = [];
    this.lastCutPolygons = [];
  }

  public getVertex(index: number): THREE.Vector3 {
    return this.model.data.getVertex(index);
  }

  public getVertices(): THREE.Vector3[] {
    return this.model.data.getVertices();
  }

  public getPolygon(index: number): number[] {
    return this.model.data.getPolygon(index);
  }

  public cut(plane: THREE.Plane): void {
    const polygons = this.model.getPolygons();
    polygons.forEach((_polygon, index) => {
      this.cutPolygon(index, plane);
    });
  }

  public cutPolygon(index: number, plane: THREE.Plane): boolean | void {
    const polygon = new Polygon(this.model.getPolygonVertices(index), this.model.data.getPolygon(index));
    if (!polygon.canCut(plane)) return false;

    this.cutpolygonPairs.push([index, this.model.getPolygons().length]);
    this.lastCutPolygons.push(this.getPolygon(index));

    const cutResult = polygon.cut(plane, this.cutpolygonNodes);
    const newCutPolygonNodes = this.model.processCutResult(index, cutResult);
    this.cutpolygonNodes = this.cutpolygonNodes.concat(newCutPolygonNodes);
  }

  public reflect(plane: THREE.Plane): void {
    this.model.shrink();
    this.resetCutHistory();
    this.cut(plane);

    this.getVertices().forEach((vertex) => {
      if (this.vertexPosition(vertex, plane) === VERTEX_POSITION.FRONT) {
        const vertexReflected = this.reflectVertex(vertex, plane);
        vertex.copy(vertexReflected);
      }
    });
  }

  public reflectIndex(plane: THREE.Plane, polygonIndex: number): void {
    const selection = this.polygonSelect(plane, polygonIndex);

    this.getVertices().forEach((vertex, index) => {
      selection.every((selectedPolygon) => {
        const polygon = this.getPolygon(selectedPolygon);
        if (polygon.indexOf(index) !== -1) {
          const vertexReflected = this.reflectVertex(vertex, plane);
          vertex.copy(vertexReflected);
          return false;
        }
        return true;
      });
    });

    this.mergeUnaffectedPolygons(selection);
    this.model.shrinkWithIndex(polygonIndex);
  }

  public crease(plane: THREE.Plane): void {
    this.fold(plane, 0);
  }

  public fold(plane: THREE.Plane, angle = 0): void {
    this.model.shrink();
    this.resetCutHistory();
    this.cut(plane);

    const foldingpoints = this.getVertices().filter((vertex) => Math.abs(plane.distanceToPoint(vertex)) < 1);
    if (foldingpoints.length === 0) return;

    const referencePoint = foldingpoints[0];
    let maxDistance = 0;
    let farpoint: THREE.Vector3 | undefined;
    let collin = false;

    foldingpoints.forEach((vertex) => {
      const distance = referencePoint.distanceTo(vertex);
      if (distance > 0) {
        collin = true;
        if (distance > maxDistance) {
          farpoint = vertex;
          maxDistance = distance;
        }
      }
    });

    if (!farpoint) return;

    for (let i = 1; i < foldingpoints.length; i++) {
      const foldingPoint = foldingpoints[i];
      if (foldingPoint === farpoint) continue;
      const v1 = referencePoint.clone().sub(foldingPoint);
      const v2 = farpoint.clone().sub(foldingPoint);
      const v3 = referencePoint.clone().sub(farpoint);
      if (v1.cross(v2).length() > v3.length()) {
        collin = false;
        break;
      }
    }

    if (collin) {
      const axis = referencePoint.clone().sub(farpoint).normalize();
      this.getVertices().forEach((vertex) => {
        if (this.vertexPosition(vertex, plane) === VERTEX_POSITION.FRONT) {
          const v2 = vertex.clone().sub(referencePoint).applyAxisAngle(axis, (angle * Math.PI) / 180).add(referencePoint);
          vertex.copy(v2);
        }
      });
    }
  }

  public foldIndex(plane: THREE.Plane, angle = 0, polygonIndex = -1): void {
    const selection = this.polygonSelect(plane, polygonIndex);
    const vertices = this.getVertices();
    const foldingpoints: THREE.Vector3[] = [];
    const foldingpointsIndices: number[] = [];

    for (let index = 0, l = vertices.length; index < l; index++) {
      const vertex = vertices[index];
      const distance = plane.distanceToPoint(vertex);
      if (Math.abs(distance) < 1) {
        for (let j = 0; j < selection.length; j++) {
          const polygon = this.getPolygon(selection[j]);
          if (polygon.indexOf(index) !== -1) {
            foldingpoints.push(vertex);
            foldingpointsIndices.push(index);
            break;
          }
        }
      }
    }

    if (foldingpoints.length === 0) return;
    const referencePoint = foldingpoints[0];
    let maxDistance = 0;
    let farpoint: THREE.Vector3 | undefined;
    let collin = false;

    foldingpoints.forEach((fp) => {
      const distance = fp.distanceTo(referencePoint);
      if (distance > 0) {
        collin = true;
        if (distance > maxDistance) {
          farpoint = fp;
          maxDistance = distance;
        }
      }
    });

    if (!farpoint) {
      this.mergeUnaffectedPolygons(selection);
      this.model.shrinkWithIndex(polygonIndex);
      return;
    }

    for (let i = 1; i < foldingpoints.length; i++) {
      const foldingPoint = foldingpoints[i];
      if (foldingPoint === farpoint) continue;
      const v1 = referencePoint.clone().sub(foldingPoint);
      const v2 = farpoint.clone().sub(foldingPoint);
      const v3 = referencePoint.clone().sub(farpoint);
      if (v1.cross(v2).length() > v3.length()) {
        collin = false;
        break;
      }
    }

    if (collin) {
      const axis = referencePoint.clone().sub(farpoint).normalize();
      this.getVertices().forEach((vertex, index) => {
        for (let i = 0; i < selection.length; i++) {
          const polygon = this.getPolygon(selection[i]);
          if (polygon.indexOf(index) !== -1) {
            const v2 = vertex.clone().sub(referencePoint).applyAxisAngle(axis, (angle * Math.PI) / 180).add(referencePoint);
            vertex.copy(v2);
            break;
          }
        }
      });
    }

    this.mergeUnaffectedPolygons(selection);
    this.model.shrinkWithIndex(polygonIndex);
  }

  public reflectVertex(vertex: THREE.Vector3, plane: THREE.Plane): THREE.Vector3 {
    return plainMath.reflection(vertex, plane);
  }

  public polygonSelect(plane: THREE.Plane, index: number): number[] {
    const selection = [index];
    for (let j = 0; j < selection.length; j++) {
      const selectedPolygon = this.getPolygon(selection[j]);
      if (selectedPolygon === undefined) {
        throw new Error("Selected Polygon Index out of bounds");
      }
      for (let i = 0; i < this.model.getPolygons().length; i++) {
        if (selection.indexOf(i) === -1) {
          const polygon = this.getPolygon(i);
          for (let ii = 0; ii < polygon.length; ii++) {
            if (selectedPolygon.indexOf(polygon[ii]) !== -1) {
              const vertex = this.getVertex(polygon[ii]);
              const distance = plane.distanceToPoint(vertex);
              if (Math.abs(distance) > 1) {
                selection.push(i);
                break;
              }
            }
          }
        }
      }
    }
    return selection;
  }

  public vertexPosition(vertex: THREE.Vector3, plane: THREE.Plane): number {
    const distance = plane.distanceToPoint(vertex);
    if (distance === 0) return VERTEX_POSITION.COPLANAR;
    return distance > 0 ? VERTEX_POSITION.FRONT : VERTEX_POSITION.BACK;
  }

  public mergeUnaffectedPolygons(selection: number[]): void {
    this.model.mergeUnaffectedPolygons(selection, this.cutpolygonPairs, this.lastCutPolygons);
    this.cutpolygonPairs = [];
    this.lastCutPolygons = [];
  }

  public reset(model: OrigamiModel): void {
    this.model = model;
    this.resetCutHistory();
    this.cutpolygonPairs = [];
    this.lastCutPolygons = [];
  }
}
