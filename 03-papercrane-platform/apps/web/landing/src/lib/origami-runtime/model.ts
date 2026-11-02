// Ported from georgiee/origami: src/origami/core/model.ts (cleaned of debug helpers)

import * as THREE from "three";
import { polygonContains } from "./math";
import { Polygon } from "./polygon";
import { OrigamiGeometryData } from "./geometry-data";
import { CutResult } from "./cut-result";

const SNAP_INTERVALS = [1 / 2];

type CutNode = { v1: number; v2: number; result: number | { added: number } };

export class OrigamiModel {
  public data: OrigamiGeometryData;

  constructor(data: OrigamiGeometryData | null = null) {
    this.data = data || new OrigamiGeometryData();
  }

  public processCutResult(index: number, result: { newpoly1: (number | { added: number })[]; newpoly2: (number | { added: number })[]; cutpolygonNodes: CutNode[]; newVertices: THREE.Vector3[] }): CutNode[] {
    const countBefore = this.data.verticesCount;

    const cr = new CutResult(result);
    cr.updateReferences(countBefore);

    this.data.addVertices(...result.newVertices);

    cr.cutpolygonNodes.forEach((node) => {
      this.amendVertices2d(node.v1, node.v2, node.result as number);
    });

    this.data.setPolygon(index, cr.newpoly1 as number[]);
    this.data.addPolygon(cr.newpoly2 as number[]);

    return cr.cutpolygonNodes;
  }

  public reset(polygons: number[][] = [], vertices: THREE.Vector3[] = [], vertices2d: THREE.Vector3[] = []): void {
    this.data.polygons = polygons;
    this.data.vertices = vertices;
    this.data.vertices2d = vertices2d;
  }

  public replaceAllPolygons(polygons: number[][]): void {
    this.data.polygons = polygons;
  }

  public clone(): OrigamiModel {
    const polygons = this.data.polygons.concat([]);
    const vertices = this.data.vertices.map((v) => v.clone());
    const vertices2d = this.data.vertices2d.map((v) => v.clone());
    const model = new OrigamiModel();
    model.reset(polygons, vertices, vertices2d);
    return model;
  }

  public mergeUnaffectedPolygons(selection: number[], cutpolygonPairs: number[][], lastCutPolygons: number[][]): void {
    cutpolygonPairs.forEach((pair, index) => {
      if (!(selection.indexOf(pair[0]) !== -1 || selection.indexOf(pair[1]) !== -1)) {
        this.data.setPolygon(pair[0], lastCutPolygons[index]);
      }
    });
    cutpolygonPairs.forEach((pair) => {
      if (!(selection.indexOf(pair[0]) !== -1 || selection.indexOf(pair[1]) !== -1)) {
        this.data.setPolygon(pair[1], []);
      }
    });
  }

  public shrink(): void {
    this.replaceAllPolygons(this.data.getPolygons().filter((polygon) => polygon.length > 0));
  }

  public shrinkWithIndex(index: number): void {
    const tmp = this.data.getPolygon(index);
    this.data.removePolygon(index);
    for (let i = 0; i < this.data.getPolygons().length; i++) {
      if (this.data.getPolygon(i).length < 1) {
        this.data.removePolygon(i);
        i--;
      }
    }
    while (index > this.data.getPolygons().length) {
      this.data.addPolygon([]);
    }
    this.data.replacePolygon(index, tmp);
  }

  public getPolygonVertices(index: number): THREE.Vector3[] {
    return this.data.getVerticesForPolygon(index);
  }

  public getPolygonVertices2d(index: number): THREE.Vector3[] {
    return this.data.getVertices2dForPolygon(index);
  }

  public findPolygon2D(point: THREE.Vector3): number {
    const polygons = this.data.getPolygons();
    const vertices2d = this.data.getVertices2d();
    const polys = polygons.map((list) => list.map((index) => [vertices2d[index].x, vertices2d[index].y] as [number, number]));
    for (let i = 0; i < polys.length; i++) {
      if (polygonContains([point.x, point.y], polys[i])) return i;
    }
    return -1;
  }

  public isStrictlyNonDegenerate(polygonIndex: number): boolean {
    const polygon = new Polygon(this.data.getVerticesForPolygon(polygonIndex));
    return polygon.isStrictlyNonDegenerate();
  }

  public isNonDegenerate(polygonIndex: number): boolean {
    const polygon = new Polygon(this.data.getVerticesForPolygon(polygonIndex));
    return polygon.isNonDegenerate();
  }

  public getPolygons(): number[][] {
    return this.data.getPolygons();
  }

  public getPolygonWrapped(): Polygon[] {
    const polygons = this.getPolygons();
    return polygons.map((indices, polygonIndex) => {
      const polygon = new Polygon();
      polygon.points = this.data.getVerticesForPolygon(polygonIndex);
      polygon.points2d = this.data.getVertices2dForPolygon(polygonIndex);
      polygon.indices = indices;
      return polygon;
    });
  }

  private amendVertices2d(v1Index: number, v2Index: number, meetIndex: number): void {
    const meet = this.data.getVertex(meetIndex);
    const v1 = this.data.getVertex(v1Index);
    const v2 = this.data.getVertex(v2Index);
    const weight1 = meet.clone().sub(v2).length();
    const weight2 = meet.clone().sub(v1).length();
    const vertex2D1 = this.data.getVertex2d(v1Index);
    const vertex2D2 = this.data.getVertex2d(v2Index);
    const vector2d = new THREE.Vector3(
      (vertex2D1.x * weight1 + vertex2D2.x * weight2) / (weight1 + weight2),
      (vertex2D1.y * weight1 + vertex2D2.y * weight2) / (weight1 + weight2),
      0,
    );
    this.data.addVertex2d(vector2d);
  }
}
