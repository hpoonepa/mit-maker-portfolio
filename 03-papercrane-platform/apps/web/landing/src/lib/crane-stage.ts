import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { buildCrane, setCraneProgress, type Crane } from "./crane-geometry";

/**
 * Real-time WebGL crane hero. Procedural origami crane built from triangular
 * paper panels with hinged pivots; folds from flat sheet to crane over a
 * scroll-locked timeline. Canvas is transparent and full-viewport so the
 * crane reads as a 3D object embedded in the page, not a video embed.
 */
export class CraneStage {
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  crane: Crane;
  clock = new THREE.Clock();
  pointer = new THREE.Vector2(0, 0);
  pointerDamp = new THREE.Vector2(0, 0);
  envMap: THREE.Texture | null = null;
  // 0..1 fold progress. Driven by autoplay timeline + scroll.
  progress = 0;
  // Auto-play seconds for the initial "load → folded crane" sequence.
  autoplayDuration = 5.5;
  autoplayElapsed = 0;
  autoplayDone = false;

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
    this.renderer.toneMappingExposure = 1.05;

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
    this.camera.position.set(2.4, 0.6, 4.6);
    this.camera.lookAt(0, 0, 0);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    pmrem.compileEquirectangularShader();
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environment = this.envMap;
    pmrem.dispose();

    // Editorial 3-light rig (warm key, cool fill, warm rim) — strong shadows
    // so paper folds read at a glance.
    const key = new THREE.DirectionalLight(0xfff4e0, 3.4);
    key.position.set(-4, 5.5, 3.2);
    this.scene.add(key);
    const fill = new THREE.HemisphereLight(0xb6c8da, 0x161412, 0.35);
    this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffe6c8, 0.85);
    rim.position.set(4.5, -1.5, -3);
    this.scene.add(rim);

    this.crane = buildCrane();
    // Scale up so the crane reads as the hero centerpiece.
    this.crane.root.scale.setScalar(1.6);
    this.scene.add(this.crane.root);
    setCraneProgress(this.crane, 0);

    this.resize();
    window.addEventListener("resize", () => this.resize());
    window.addEventListener("pointermove", (e) => {
      this.pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      this.pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
    });
    window.addEventListener("scroll", () => this.onScroll(), { passive: true });

    (window as unknown as { __crane: CraneStage }).__crane = this;
    this.renderer.setAnimationLoop(() => this.tick());
  }

  onScroll(): void {
    if (!this.autoplayDone) return;
    const max = window.innerHeight * 1.2; // first ~120vh of scroll drives fold reverse
    const sy = Math.max(0, Math.min(max, window.scrollY));
    // Allow scroll to UNFOLD slightly (1 → 0.55) so user sees motion as they scroll.
    this.progress = 1 - (sy / max) * 0.45;
    setCraneProgress(this.crane, this.progress);
  }

  resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  tick(): void {
    const dt = Math.min(this.clock.getDelta(), 1 / 30);

    if (!this.autoplayDone) {
      this.autoplayElapsed += dt;
      const t = Math.min(1, this.autoplayElapsed / this.autoplayDuration);
      this.progress = t;
      setCraneProgress(this.crane, t);
      if (t >= 1) {
        this.autoplayDone = true;
      }
    }

    // Cursor parallax + idle motion on the crane root.
    const damp = 1 - Math.pow(0.0001, dt);
    this.pointerDamp.x += (this.pointer.x - this.pointerDamp.x) * damp;
    this.pointerDamp.y += (this.pointer.y - this.pointerDamp.y) * damp;
    // Slight 3/4-view rotation already applied via camera position; add gentle
    // drift + pointer parallax for liveliness.
    this.crane.root.rotation.y =
      0.3 + this.pointerDamp.x * 0.45 + Math.sin(this.clock.elapsedTime * 0.18) * 0.12;
    this.crane.root.rotation.x = -0.05 + this.pointerDamp.y * 0.18;
    this.crane.root.position.y = Math.sin(this.clock.elapsedTime * 0.5) * 0.08;

    this.renderer.render(this.scene, this.camera);
  }
}
