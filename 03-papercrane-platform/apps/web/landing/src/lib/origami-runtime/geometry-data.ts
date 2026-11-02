// Ported from georgiee/origami: src/origami/core/geometry-data.ts

import * as THREE from "three";

export class OrigamiGeometryData {
  public vertices: THREE.Vector3[] = [];
  public vertices2d: THREE.Vector3[] = [];
  public polygons: number[][] = [];

  public getVerticesForPolygon(index: number): THREE.Vector3[] {
    return this.polygons[index].map((polygonIndex) => this.vertices[polygonIndex]);
  }

  public getVertices2dForPolygon(index: number): THREE.Vector3[] {
    return this.polygons[index].map((vertexIndex) => this.vertices2d[vertexIndex]);
  }

  get verticesCount(): number {
    return this.vertices.length;
  }

  public addVertices(...vertices: THREE.Vector3[]): void {
    this.vertices.push(...vertices);
  }

  public getPolygons(): number[][] {
    return this.polygons.concat([]);
  }

  public getPolygon(index: number): number[] {
    return this.polygons[index];
  }

  public setPolygon(index: number, polygon: number[]): void {
    this.polygons[index] = polygon;
  }

  public addPolygon(polygon: number[]): void {
    this.polygons.push(polygon);
  }

  public removePolygon(index: number): number[][] {
    return this.polygons.splice(index, 1);
  }

  public replacePolygon(index: number, tmp: number[]): void {
    this.polygons.splice(index, 0, tmp);
  }

  public getVertex(index: number): THREE.Vector3 {
    return this.vertices[index];
  }

  public addVertex(v: THREE.Vector3): void {
    this.vertices.push(v);
  }

  public getVertices(): THREE.Vector3[] {
    return this.vertices.concat([]);
  }

  public getVertex2d(index: number): THREE.Vector3 {
    return this.vertices2d[index];
  }

  public addVertex2d(v: THREE.Vector3): void {
    this.vertices2d.push(v);
  }

  public getVertices2d(): THREE.Vector3[] {
    return this.vertices2d.concat([]);
  }
}
