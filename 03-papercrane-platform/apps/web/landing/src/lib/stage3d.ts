import * as THREE from "three";
import { Signal } from "./signal";

export abstract class Stage3D {
  scene = new THREE.Scene();
  isActive = true;
  ratio = 0;
  onBeforeRender = new Signal<number>();
  onAfterRender = new Signal<number>();

  abstract preInit(): void | Promise<void>;
  abstract init(): void;
  abstract resize(w: number, h: number): void;
  abstract update(dt: number): void;
  dispose(): void {
    this.onBeforeRender.clear();
    this.onAfterRender.clear();
  }
}

export const visuals = {
  stage3DList: [] as Stage3D[],
};
