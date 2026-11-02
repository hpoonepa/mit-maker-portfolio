import * as THREE from "three";
import { Stage3D } from "../../stage3d";
import { createMorphPaperGeometry } from "../../geometry/morph-paper";
import { getPaperGrainNormalMap } from "../../render/paper-grain";
import { getSeedRandomFn } from "../../math/seed-random";
import {
  SPHERES_DATA,
  type StructureSpec,
  type PaperVariant,
} from "./spheres-data";
import { COLORS } from "./palettes";
import { Physics } from "../../physics/physics";
import { Body } from "../../physics/body";
import { MouseForce } from "../../physics/mouse-force";
import { properties } from "../../properties";
import { changeHomeHeroColorSignal } from "../../signals";

function resolveColor(spec: StructureSpec, fancyIdx: number): THREE.Color {
  return new THREE.Color(spec.color === "fancy" ? COLORS[fancyIdx] : spec.color);
}

type FoldPhase = "idle" | "fold" | "hold" | "unfold";

type PaperBody = {
  spec: StructureSpec;
  body: Body;
  mesh: THREE.Mesh;
  mat: THREE.MeshStandardMaterial;
  foldPhase: FoldPhase;
  foldElapsed: number; // seconds in current phase
};

const FOLD_DURATION = 1.2;
const HOLD_DURATION = 2.0;
const UNFOLD_DURATION = 1.2;

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

const VARIANT_DIMS: Record<PaperVariant, { width: number; height: number; jagged: number; curl: number }> = {
  small: { width: 0.85, height: 0.6, jagged: 0.04, curl: 0.05 },
  medium: { width: 1.15, height: 0.78, jagged: 0.06, curl: 0.08 },
  large: { width: 1.45, height: 0.95, jagged: 0.08, curl: 0.11 },
};

// Geometry cache: same variant -> reused geometry across instances.
const GEOM_CACHE = new Map<PaperVariant, THREE.BufferGeometry>();
function geomFor(variant: PaperVariant): THREE.BufferGeometry {
  const cached = GEOM_CACHE.get(variant);
  if (cached) return cached;
  const d = VARIANT_DIMS[variant];
  const g = createMorphPaperGeometry({
    width: d.width,
    height: d.height,
    jaggedness: d.jagged,
    curlAmount: d.curl,
    seed: `morph-${variant}`,
  });
  GEOM_CACHE.set(variant, g);
  return g;
}

export class HomeBalloons extends Stage3D {
  NUM_BALLOONS = SPHERES_DATA.length;
  papers: PaperBody[] = [];
  physics = new Physics();
  mouseForce = new MouseForce();
  camera: THREE.PerspectiveCamera;
  private raycaster = new THREE.Raycaster();
  private clickNDC = new THREE.Vector2();

  constructor(camera: THREE.PerspectiveCamera) {
    super();
    this.camera = camera;
  }

  async preInit(): Promise<void> {
    const rand = getSeedRandomFn("balloonBody-25");
    for (const spec of SPHERES_DATA) {
      this.physics.bodies.push(
        new Body(
          spec.radius,
          spec.density,
          spec.friction,
          spec.restitution,
          spec.isSemitransparent,
          rand,
        ),
      );
    }
  }

  init(): void {
    properties.balloonsColorIndex = Math.floor(Math.random() * COLORS.length);
    const grain = getPaperGrainNormalMap();
    // Debug hook
    (window as unknown as { __balloons: HomeBalloons }).__balloons = this;

    for (let i = 0; i < SPHERES_DATA.length; i++) {
      const spec = SPHERES_DATA[i];
      const body = this.physics.bodies[i];
      const geom = geomFor(spec.variant);

      const mat = new THREE.MeshStandardMaterial({
        color: resolveColor(spec, properties.balloonsColorIndex),
        metalness: 0.0,
        roughness: 0.78 + Math.random() * 0.14,
        envMapIntensity: 0.35,
        side: THREE.DoubleSide,
        normalMap: grain,
        normalScale: new THREE.Vector2(0.6, 0.6),
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.morphTargetInfluences = [0];
      mesh.userData.bodyIdx = i;
      this.scene.add(mesh);

      this.papers.push({
        spec,
        body,
        mesh,
        mat,
        foldPhase: "idle",
        foldElapsed: 0,
      });
    }

    // Lighting (kept warm key + cool fill).
    const key = new THREE.DirectionalLight(0xfff4e0, 4.5);
    key.position.set(-5, 6, 5);
    this.scene.add(key);
    const fill = new THREE.HemisphereLight(0x95a8c0, 0x080808, 0.5);
    this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffe6c8, 0.8);
    rim.position.set(4, -2, -4);
    this.scene.add(rim);

    this.mouseForce.bind();
    this.recomputeBounds();

    changeHomeHeroColorSignal.add(() => {
      properties.balloonsColorIndex =
        (properties.balloonsColorIndex + 1) % COLORS.length;
      const fancy = new THREE.Color(COLORS[properties.balloonsColorIndex]);
      for (const p of this.papers) {
        if (p.spec.isColored) p.mat.color.copy(fancy);
      }
    });
  }

  /**
   * Public entry: try to trigger a fold for whichever sheet was clicked.
   * Returns true if a sheet was hit and triggered, false otherwise.
   */
  triggerFoldAt(clientX: number, clientY: number): boolean {
    this.clickNDC.x = (clientX / window.innerWidth) * 2 - 1;
    this.clickNDC.y = -(clientY / window.innerHeight) * 2 + 1;
    this.raycaster.setFromCamera(this.clickNDC, this.camera);
    const meshes = this.papers.map((p) => p.mesh);
    const hits = this.raycaster.intersectObjects(meshes, false);
    if (hits.length === 0) return false;
    const hit = hits[0].object as THREE.Mesh;
    const idx = hit.userData.bodyIdx as number;
    const p = this.papers[idx];
    if (p.foldPhase !== "idle") return false;
    p.foldPhase = "fold";
    p.foldElapsed = 0;
    return true;
  }

  resize(): void {
    this.recomputeBounds();
  }

  recomputeBounds(): void {
    const fovRad = (this.camera.fov * Math.PI) / 180;
    const halfH = Math.tan(fovRad / 2) * Math.abs(this.camera.position.z);
    const halfW = halfH * this.camera.aspect;
    this.physics.bounds = {
      x: halfW * 4.5,
      y: halfH * 4.5,
      z: 3.5,
    };
  }

  private updateFold(p: PaperBody, dt: number): void {
    if (p.foldPhase === "idle") return;
    p.foldElapsed += dt;
    let influence = 0;
    if (p.foldPhase === "fold") {
      const t = Math.min(1, p.foldElapsed / FOLD_DURATION);
      influence = easeInOutCubic(t);
      if (t >= 1) {
        p.foldPhase = "hold";
        p.foldElapsed = 0;
      }
    } else if (p.foldPhase === "hold") {
      influence = 1;
      if (p.foldElapsed >= HOLD_DURATION) {
        p.foldPhase = "unfold";
        p.foldElapsed = 0;
      }
    } else if (p.foldPhase === "unfold") {
      const t = Math.min(1, p.foldElapsed / UNFOLD_DURATION);
      influence = 1 - easeInOutCubic(t);
      if (t >= 1) {
        p.foldPhase = "idle";
        p.foldElapsed = 0;
        influence = 0;
      }
    }
    if (p.mesh.morphTargetInfluences) p.mesh.morphTargetInfluences[0] = influence;
  }

  update(dt: number): void {
    this.recomputeBounds();
    this.physics.update(dt);
    this.mouseForce.apply(this.physics.bodies, this.camera);

    for (const p of this.papers) {
      p.mesh.position.copy(p.body.position);
      p.mesh.quaternion.copy(p.body.quaternion);
      p.mesh.scale.setScalar(p.body.radius);
      this.updateFold(p, dt);
    }
  }
}
