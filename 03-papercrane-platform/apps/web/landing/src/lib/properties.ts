import * as THREE from "three";

export const properties = {
  time: 0,
  dt: 1 / 60,
  width: 0,
  height: 0,
  viewportWidth: 0,
  viewportHeight: 0,
  dpr: 1,
  hasInitialized: false,
  camera: null as THREE.PerspectiveCamera | null,
  scrollProgress: 0,
  balloonsColorIndex: 0,
};
