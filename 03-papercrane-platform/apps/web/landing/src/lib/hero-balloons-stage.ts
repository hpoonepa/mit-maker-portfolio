import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { Physics } from "./physics/physics";
import { Body } from "./physics/body";
import { MouseForce } from "./physics/mouse-force";
import { getSeedRandomFn } from "./math/seed-random";
import { COLORS } from "./stages/balloons/palettes";
import { getCraneGeometry } from "./origami-runtime/build-crane";
import { getPaperGrainNormalMap } from "./render/paper-grain";
import { PaperCraneActor } from "./webgl/paper-crane-actor";

type Inst = {
  body: Body;
  actor: PaperCraneActor;
  isFancy: boolean;
};

const N = typeof window !== "undefined" && window.innerWidth < 720 ? 44 : 76;
const GREEN = "#1f4438";
const CREAM = "#eadfc5";
const RUST = "#7a4b1c";
const INK = "#171714";

/**
 * Hero cluster: paper-crane silhouettes orbiting the title.
 * Geometry is baked at runtime from /origami/crane.json (georgiee/origami
 * playbook commands replayed against a square sheet).
 *
 *   - Shell-spring physics — bodies sit on an ellipsoid hugging the title.
 *   - MouseForce: smoothstep falloff, linear speed scaling (no cap).
 *   - Click on the canvas cycles through the verified Lusion 9-color palette;
 *     only "fancy" bodies pick up the new color.
 */
export class HeroBalloonsStage {
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  physics = new Physics();
  mouseForce = new MouseForce();
  insts: Inst[] = [];
  clock = new THREE.Clock();
  envMap: THREE.Texture | null = null;
  colorIndex = Math.floor(Math.random() * COLORS.length);
  reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  constructor(public canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.setClearAlpha(0);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;

    this.camera = new THREE.PerspectiveCamera(25, 1, 1, 200);
    this.camera.position.set(0, 0, 16);
    this.camera.lookAt(0, 0, 0);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    pmrem.compileEquirectangularShader();
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.02).texture;
    this.scene.environment = this.envMap;
    pmrem.dispose();

    const key = new THREE.RectAreaLight(0xfff1d7, 18, 6.5, 5.5);
    key.position.set(-4.5, 5.5, 6);
    key.lookAt(0, 0, 0);
    this.scene.add(key);
    const fill = new THREE.HemisphereLight(0xc5d5d0, 0x241c16, 0.72);
    this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffd6a6, 1.35);
    rim.position.set(4, -2, -4);
    this.scene.add(rim);
    const coolEdge = new THREE.DirectionalLight(0x9fbeb7, 0.7);
    coolEdge.position.set(-4, 1, -5);
    this.scene.add(coolEdge);

    // Disable gravity-to-origin — the title sits at origin, so we don't want
    // bodies trying to pile there. Shell-spring (in tick) holds them on a
    // hollow sphere around the title.
    this.physics.gravityFactor = 0;
    this.physics.linearDamping = 0.13;
    this.physics.angularDamping = 0.08;

    const rand = getSeedRandomFn("balloonBody-25");
    // Load the articulated crane asset. It uses the same origami model as the
    // static playbook, but preserves its skeleton so each bird can breathe and
    // partially unfold on an independent timeline.
    const craneRadius = 0.41;
    void new GLTFLoader()
      .loadAsync("/_landing/crane.glb")
      .then((gltf) => this.attachActors(gltf.scene, gltf.animations[0], rand))
      .catch(() =>
        getCraneGeometry(craneRadius).then((geom) => this.attachFallback(geom, rand)),
      );

    // Size spawn extents to the live canvas BEFORE placing bodies so the flock
    // fills the full-bleed hero from the first frame. (ResizeObserver + the
    // window resize listener below keep it filled on later size changes.)
    this.resize();

    for (let i = 0; i < N; i++) {
      const radius = craneRadius * (0.78 + rand() * 0.52);
      const body = new Body(radius, 1.0, 2, 0.2, false, rand);
      // A crane reads best with its spine near the screen plane. Keep the
      // physical spin slow enough to preserve that silhouette between banks.
      body.angularVelocity.multiplyScalar(0.1);
      this.physics.bodies.push(body);

      // Halton-sequence spawn for even, low-discrepancy distribution across
      // the hero volume — eliminates the clumps random sampling produces.
      this.placeHalton(body, i, rand);
      body.velocity.set(
        (rand() - 0.5) * 0.3,
        (rand() - 0.5) * 0.3,
        (rand() - 0.5) * 0.3,
      );

      // Per-body float seeds: independent random phase per axis + a small
      // per-body frequency jitter so the flock drifts asynchronously.
      this.floatSeeds.push({
        phase: new THREE.Vector3(
          rand() * Math.PI * 2,
          rand() * Math.PI * 2,
          rand() * Math.PI * 2,
        ),
        speed: 0.85 + rand() * 0.4,
      });
    }

    if (!this.reducedMotion) this.mouseForce.bind();
    this.canvas.addEventListener("click", () => this.cycleColor());

    this.resize();
    const ro = new ResizeObserver(() => this.resize());
    if (canvas.parentElement) ro.observe(canvas.parentElement);
    window.addEventListener("resize", () => this.resize());
    this.renderer.setAnimationLoop(() => this.tick());
  }

  cycleColor(): void {
    this.colorIndex = (this.colorIndex + 1) % COLORS.length;
    const fancy = new THREE.Color(COLORS[this.colorIndex]);
    for (const inst of this.insts) {
      if (inst.isFancy) inst.actor.setColor(fancy);
    }
  }

  attachActors(
    source: THREE.Object3D,
    clip: THREE.AnimationClip | undefined,
    rand: () => number,
  ): void {
    const paperGrain = getPaperGrainNormalMap();

    // Normalize once from the asset's composed folded pose. Every actor then
    // uses its physics radius as a clean, predictable scale multiplier.
    const bounds = new THREE.Box3().setFromObject(source);
    const size = bounds.getSize(new THREE.Vector3());
    const modelScale = 0.82 / Math.max(size.x, size.y, size.z, 0.001);
    const center = bounds.getCenter(new THREE.Vector3());
    source.position.sub(center);

    for (let i = 0; i < this.physics.bodies.length; i++) {
      const body = this.physics.bodies[i];
      const tone = rand();
      const isFancy = tone < 0.58;
      const color = isFancy ? GREEN : tone < 0.78 ? CREAM : tone < 0.92 ? RUST : INK;
      const actor = new PaperCraneActor(source, clip, {
        color,
        grain: paperGrain,
        scale: modelScale * (body.radius / 0.41),
        seed: rand(),
        featured: i % 7 === 0,
        colored: isFancy,
      });
      body.quaternion.setFromEuler(
        new THREE.Euler(
          Math.PI * 0.5 + (rand() - 0.5) * 0.5,
          (rand() - 0.5) * 0.7,
          rand() * Math.PI * 2,
        ),
      );
      actor.root.quaternion.copy(body.quaternion);
      this.scene.add(actor.root);
      this.insts.push({ body, actor, isFancy });
    }
  }

  attachFallback(geom: THREE.BufferGeometry, rand: () => number): void {
    const source = new THREE.Group();
    source.add(new THREE.Mesh(geom));
    this.attachActors(source, undefined, rand);
  }

  resize(): void {
    const parent = this.canvas.parentElement;
    if (!parent) return;
    const rect = parent.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    if (w < 4 || h < 4) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();

    const fovRad = (this.camera.fov * Math.PI) / 180;
    const halfH = Math.tan(fovRad / 2) * Math.abs(this.camera.position.z);
    const halfW = halfH * this.camera.aspect;

    // Track the actual canvas edges on BOTH axes so the flock fills the
    // full-bleed hero: x = visible half-width, y/top = visible half-height.
    const prevX = this.shellExtent.x;
    const prevY = this.shellExtent.y;
    this.shellExtent.x = halfW * this.shellMarginX;
    this.shellExtent.y = halfH * this.shellMarginY;
    this.shellExtentTop = halfH * this.shellMarginY;

    // Rescale already-placed homes so a resize re-fills the new extent rather
    // than leaving the flock clustered at the previous width/height.
    if (this.physics.bodies.length && prevX > 0 && prevY > 0) {
      const sx = this.shellExtent.x / prevX;
      const sy = this.shellExtent.y / prevY;
      for (const body of this.physics.bodies) {
        body.position0.x *= sx;
        body.position.x *= sx;
        body.position0.y *= sy;
        body.position.y *= sy;
      }
    }

    this.physics.bounds = {
      x: halfW * 4.5,
      y: halfH * 4.5,
      z: 3.5,
    };
  }

  // Spawn volume: half-extents of the visible hero region.
  // x is recomputed in resize() to match the canvas halfW. y reaches both
  // top and bottom canvas edges so cranes fill the entire visible area.
  shellMarginX = 0.99;
  shellMarginY = 0.98; // reach the top + bottom borders too (full-bleed hero)
  shellExtent = { x: 6, y: 3.4, z: 1.4 };
  shellExtentTop = 3.4; // reach the top border

  // Title exclusion box (xy only, z is ignored). Cranes anywhere within this
  // rectangle in world-space xy project onto the headline in screen space —
  // CSS stacks the title above the canvas, so cranes there are hidden by
  // letterforms but show through gaps. Excluding the full bbox kills that.
  titleExclude = { x: 4.2, y: 1.7 };
  titleStiffness = 60;
  // How strongly each crane is pulled back to its spawn position when
  // disturbed (mouse fling, etc.). 0 = no return; higher = snappier return.
  homeStiffness = 5;

  // Continuous slow float — sinusoidal velocity per axis + per-body phase so
  // every crane drifts gently around its home, like floating in still air.
  floatAmp = 0.55;
  floatSeeds: { phase: THREE.Vector3; speed: number }[] = [];
  elapsedTime = 0;

  // Place body at a random position inside the spawn volume but outside the
  // title exclusion. Tries a few times; falls back to a guaranteed-outside
  // edge if every random pick lands in the title.
  // Low-discrepancy point in [0, 1) — Halton sequence in given prime base.
  private halton(index: number, base: number): number {
    let result = 0;
    let f = 1 / base;
    let i = index;
    while (i > 0) {
      result += f * (i % base);
      i = Math.floor(i / base);
      f /= base;
    }
    return result;
  }

  placeHalton(body: Body, idx: number, rand: () => number): void {
    // Use the i-th Halton point on bases (2, 3, 5) to get a deterministic,
    // evenly-spread position. If the point lands inside the title exclusion,
    // try a few neighboring sequence indices before falling back.
    let i = idx + 1;
    for (let attempt = 0; attempt < 30; attempt++) {
      const ux = this.halton(i, 2);
      const uy = this.halton(i, 3);
      const uz = this.halton(i, 5);

      const x = (ux - 0.5) * 2 * this.shellExtent.x;
      // Bias more cranes toward the top — 65% of bodies sit above the title.
      const topBias = 0.65;
      const y =
        uy < 1 - topBias
          ? -(1 - topBias - uy) / (1 - topBias) * this.shellExtent.y
          : ((uy - (1 - topBias)) / topBias) * this.shellExtentTop;
      const z = (uz - 0.5) * 2 * this.shellExtent.z;

      const inX = Math.abs(x) < this.titleExclude.x;
      const inY = Math.abs(y) < this.titleExclude.y;
      // Top-left rarefaction: reject ~55% of top-left placements (x<0, y>0)
      // so that quadrant reads sparser than the rest. Uses Halton base 7
      // for the accept/reject draw to keep the sampling deterministic.
      const isTopLeft = x < 0 && y > 0;
      const reject = isTopLeft && this.halton(i, 7) < 0.55;
      if (!(inX && inY) && !reject) {
        body.position.set(x, y, z);
        body.position0.copy(body.position);
        return;
      }
      i += this.physics.bodies.length; // jump forward in the sequence
    }
    // Fallback: park just above/below the title.
    const sign = rand() > 0.5 ? 1 : -1;
    body.position.set(
      (rand() - 0.5) * 2 * this.shellExtent.x,
      sign * (this.titleExclude.y + 0.4),
      (rand() - 0.5) * 2 * this.shellExtent.z,
    );
    body.position0.copy(body.position);
  }

  tick(): void {
    const dt = Math.min(this.clock.getDelta(), 1 / 30);
    this.elapsedTime += dt;

    // Title exclusion: any crane inside the title's xy bbox gets pushed out
    // along the closest edge. z is ignored — CSS stacks the title above the
    // canvas so anything in the title's xy footprint is hidden anyway.
    const tx = this.titleExclude.x;
    const ty = this.titleExclude.y;
    const hk = this.homeStiffness;
    const t = this.elapsedTime;
    const fAmp = this.floatAmp;
    if (!this.reducedMotion) {
      for (let i = 0; i < this.physics.bodies.length; i++) {
        const body = this.physics.bodies[i];
        const ax = Math.abs(body.position.x);
        const ay = Math.abs(body.position.y);
        if (ax < tx && ay < ty) {
          const distX = tx - ax;
          const distY = ty - ay;
          if (distX < distY) {
            body.velocity.x +=
              Math.sign(body.position.x) * this.titleStiffness * distX * dt;
          } else {
            body.velocity.y +=
              Math.sign(body.position.y) * this.titleStiffness * distY * dt;
          }
        }

        // Restoring spring: pull each body back to its spawn position.
        body.velocity.x += (body.position0.x - body.position.x) * hk * dt;
        body.velocity.y += (body.position0.y - body.position.y) * hk * dt;
        body.velocity.z += (body.position0.z - body.position.z) * hk * dt;

        // Continuous slow float — sinusoidal velocity with a per-body phase
        // and frequency. Different angular frequencies per axis (0.6 / 0.5 /
        // 0.4 rad/s) so the drift never repeats exactly.
        const seed = this.floatSeeds[i];
        if (seed) {
          const sp = seed.speed;
          body.velocity.x +=
            Math.sin(t * 0.6 * sp + seed.phase.x) * fAmp * dt;
          body.velocity.y +=
            Math.cos(t * 0.5 * sp + seed.phase.y) * fAmp * dt;
          body.velocity.z +=
            Math.sin(t * 0.4 * sp + seed.phase.z) * fAmp * 0.6 * dt;
        }
      }

      this.physics.update(dt);
      this.mouseForce.apply(this.physics.bodies, this.camera);
    }

    for (const inst of this.insts) {
      inst.actor.root.position.copy(inst.body.position);
      inst.actor.root.quaternion.copy(inst.body.quaternion);
      inst.actor.update(this.elapsedTime, inst.body.position.z, this.reducedMotion);
    }

    this.renderer.render(this.scene, this.camera);
  }
}
