// Ported from georgiee/origami: src/origami/core/polygon.ts

import * as THREE from "three";
import * as math from "./math";
import * as plainMath from "./plain-math";

function* range(begin: number, end: number, interval = 1) {
  for (let i = begin; i < end; i += interval) yield i;
}

type CutNode = { v1: number; v2: number; result: number | { added: number } };

export class Polygon {
  public points: THREE.Vector3[];
  public points2d: THREE.Vector3[] = [];
  public indices: number[];

  constructor(points: THREE.Vector3[] = [], indices: number[] | null = null) {
    if (indices === null) {
      indices = Array.from(range(0, points.length, 1));
    }
    this.points = points.concat([]);
    this.indices = indices.concat([]);
  }

  public getNormal(): THREE.Vector3 {
    const normal = new THREE.Vector3();
    const length = this.points.length;
    for (let i = 0; i < length; i++) {
      const current = this.points[i];
      const next = this.points[(i + 1) % length];
      normal.x = normal.x + (current.y - next.y) * (current.z + next.z);
      normal.y = normal.y + (current.z - next.z) * (current.x + next.x);
      normal.z = normal.z + (current.x - next.x) * (current.y + next.y);
    }
    return normal.normalize();
  }

  public getPoints(): THREE.Vector3[] {
    return this.points;
  }

  public getPoints2d(): THREE.Vector3[] {
    return this.points2d;
  }

  public isStrictlyNonDegenerate(): boolean {
    if (this.size < 3) return false;
    const points = this.points;
    const l = this.size;
    const basePoint = this.points[0];

    for (let i = 0; i < l; i++) {
      const pointA = points[i];
      for (let j = 0; j < l; j++) {
        const pointB = points[j];
        const directionA = pointA.clone().sub(basePoint);
        const directionB = pointB.clone().sub(basePoint);
        const area = new THREE.Vector3().crossVectors(directionA, directionB).length();
        if (area > 0) return true;
      }
    }
    return false;
  }

  public isNonDegenerate(): boolean {
    const size = this.size;
    if (size > 1) {
      for (let i = 0; i < size; i++) {
        if (this.points[0].distanceTo(this.points[i]) > 0) return true;
      }
    }
    return false;
  }

  public getPreviousCuts(cuts: CutNode[], i: number, j: number): number | { added: number } | null {
    const polygonIndices = this.indices;
    const equal = (node: CutNode, index1: number, index2: number) => {
      return (node.v1 === index1 && node.v2 === index2) || (node.v1 === index2 && node.v2 === index1);
    };
    for (const node of cuts) {
      if (equal(node, polygonIndices[i], polygonIndices[j])) return node.result;
    }
    return null;
  }

  public cut(plane: THREE.Plane, previousCuts: CutNode[] = []): {
    newpoly1: (number | { added: number })[];
    newpoly2: (number | { added: number })[];
    newVertices: THREE.Vector3[];
    cutpolygonNodes: CutNode[];
  } {
    const size = this.size;
    const indices = this.indices;
    const ppoint = plane.coplanarPoint(new THREE.Vector3());
    const pnormal = plane.normal;
    const newpoly1: (number | { added: number })[] = [];
    const newpoly2: (number | { added: number })[] = [];
    const newVertices: THREE.Vector3[] = [];
    const cutpolygonNodes: CutNode[] = [];

    for (let i = 0; i < size; i++) {
      const j = (i + 1) % size;
      const vertex = this.points[i];
      const vertex2 = this.points[j];
      const distance = plane.distanceToPoint(vertex);

      if (Math.abs(distance) < 1) {
        newpoly1.push(indices[i]);
        newpoly2.push(indices[i]);
      } else {
        const sideA = vertex.dot(pnormal);
        const sideB = ppoint.dot(pnormal);
        if (sideA > sideB) newpoly1.push(indices[i]);
        else newpoly2.push(indices[i]);

        const divided = math.planeBetweenPoints3(plane, vertex, vertex2);
        const onPlane = math.pointOnPlane(plane, vertex2);
        const combinedTest = divided && !onPlane;

        if (combinedTest) {
          const previousCut = this.getPreviousCuts(previousCuts, i, j);
          if (previousCut !== null) {
            newpoly1.push(previousCut);
            newpoly2.push(previousCut);
          } else {
            const direction = vertex.clone().sub(vertex2);
            const line = new THREE.Line3(vertex, vertex2);
            if (plane.intersectsLine(line)) {
              const meetRaw = plainMath.linePlaneIntersection(line.start, direction, plane);
              const meet = new THREE.Vector3(meetRaw[0], meetRaw[1], meetRaw[2]);
              newVertices.push(meet);
              const ref = { added: newVertices.length - 1 };
              newpoly1.push(ref);
              newpoly2.push(ref);
              cutpolygonNodes.push({ v1: indices[i], v2: indices[j], result: ref });
            }
          }
        }
      }
    }

    return { newpoly1, newpoly2, newVertices, cutpolygonNodes };
  }

  public canCut(plane: THREE.Plane): boolean {
    if (!this.isNonDegenerate()) return false;
    let inner = false;
    let outer = false;
    const normal = plane.normal;
    const coplanarPoint = plane.coplanarPoint(new THREE.Vector3());

    for (let i = 0; i < this.size; i++) {
      const point = this.points[i];
      const normalLength = Math.sqrt(Math.max(1, normal.lengthSq()));
      if (point.dot(normal) / normalLength > coplanarPoint.dot(normal) / normalLength + 0.00000001) inner = true;
      else if (point.dot(normal) / normalLength < coplanarPoint.dot(normal) / normalLength - 0.00000001) outer = true;
      if (inner && outer) return true;
    }
    return false;
  }

  public get size(): number {
    return this.points.length;
  }

  public triangulate(): number[][] {
    // 1. Rotate the polygon so it lies in the XY plane (so we can drop z).
    const aligned = this.alignWithXYPlane(this.points);
    // 2. Convert to Vector2 — triangulateShape expects 2D contour input.
    const contour = aligned.map((v) => new THREE.Vector2(v.x, v.y));
    return THREE.ShapeUtils.triangulateShape(contour, []);
  }

  private alignWithXYPlane(vertices: THREE.Vector3[]): THREE.Vector3[] {
    const axisZ = new THREE.Vector3(0, 0, 1);
    const polygonNormal = new Polygon(vertices).getNormal();
    const dot = axisZ.dot(polygonNormal);

    // Already aligned with +Z — no rotation needed.
    if (dot > 1 - 1e-6) return vertices.map((v) => v.clone());

    // Anti-parallel — flip 180° around any perpendicular axis (X works).
    if (dot < -1 + 1e-6) {
      const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI);
      return vertices.map((v) => v.clone().applyQuaternion(q));
    }

    const rotationAxis = new THREE.Vector3().crossVectors(polygonNormal, axisZ).normalize();
    const theta = Math.acos(dot);
    const quaternion = new THREE.Quaternion().setFromAxisAngle(rotationAxis, theta);
    return vertices.map((vector) => vector.clone().applyQuaternion(quaternion));
  }
}
