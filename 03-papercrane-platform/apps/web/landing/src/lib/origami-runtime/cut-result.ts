// Ported from georgiee/origami: src/origami/core/cut-result.ts

import type * as THREE from "three";

type AddedRef = { added: number };
type RefOrIndex = number | AddedRef;

function isAddedRef(o: RefOrIndex): o is AddedRef {
  return typeof o === "object" && (o as AddedRef).added !== undefined;
}

export class CutResult {
  public newpoly1: RefOrIndex[];
  public newpoly2: RefOrIndex[];
  public cutpolygonNodes: { v1: number; v2: number; result: AddedRef | number }[];
  public newVertices: THREE.Vector3[];

  constructor({ newpoly1 = [], newpoly2 = [], cutpolygonNodes = [], newVertices = [] }: {
    newpoly1?: RefOrIndex[];
    newpoly2?: RefOrIndex[];
    cutpolygonNodes?: { v1: number; v2: number; result: AddedRef | number }[];
    newVertices?: THREE.Vector3[];
  }) {
    this.newpoly1 = newpoly1;
    this.newpoly2 = newpoly2;
    this.cutpolygonNodes = cutpolygonNodes;
    this.newVertices = newVertices;
  }

  public expandIndex(baseSize: number) {
    return (object: RefOrIndex): number => {
      if (isAddedRef(object)) return object.added + baseSize;
      return object;
    };
  }

  public updateReferences(baseSize: number): void {
    this.newpoly1 = this.newpoly1.map(this.expandIndex(baseSize));
    this.newpoly2 = this.newpoly2.map(this.expandIndex(baseSize));
    this.cutpolygonNodes = this.cutpolygonNodes.map((node) => {
      const result = isAddedRef(node.result as RefOrIndex)
        ? (node.result as AddedRef).added + baseSize
        : (node.result as number);
      return Object.assign(node, { result });
    });
  }
}
