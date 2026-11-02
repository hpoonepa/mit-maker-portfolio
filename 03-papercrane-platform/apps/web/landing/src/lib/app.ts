import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { properties } from "./properties";
import { visuals } from "./stage3d";
import { scrollManager } from "./scroll/scroll-manager";
import { math } from "./math";
import { HomeBalloons } from "./stages/balloons";
import { HomeHeroSection } from "./ui/home-hero-section";
import { changeHomeHeroColorSignal } from "./signals";

export class App {
  renderer: THREE.WebGLRenderer;
  camera: THREE.PerspectiveCamera;
  clock = new THREE.Clock();
  envMap: THREE.Texture | null = null;
  homeBalloons!: HomeBalloons;
  homeHeroSection!: HomeHeroSection;
  domHomeHero: HTMLElement | null = null;
  domPreloader: HTMLElement | null = null;
  bootCountdown = 0.6; // brief preload before fade

  constructor() {
    const canvas = document.getElementById("canvas") as HTMLCanvasElement;
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.setClearAlpha(0);
    this.renderer.autoClear = true;

    properties.dpr = Math.min(window.devicePixelRatio, 2);
    this.renderer.setPixelRatio(properties.dpr);

    // Verified from Lusion: cameraFov=25, cameraNear=0.1, cameraFar=200.
    // Note: bundle states camera at origin; in practice we offset to (0,0,12) so the
    // cluster (which converges on origin) sits in front of the camera. Documented gap.
    this.camera = new THREE.PerspectiveCamera(25, 1, 1, 200);
    this.camera.position.set(0, 0, 16);
    this.camera.lookAt(0, 0, 0);
    properties.camera = this.camera;

    this.setupEnv();
    this.bootstrapStages();
    this.setupScroll();
    this.setupClick();
    this.preloaderRef();

    this.resize();
    window.addEventListener("resize", () => this.resize());

    properties.hasInitialized = true;
    this.renderer.setAnimationLoop(() => this.tick());
  }

  setupEnv(): void {
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    pmrem.compileEquirectangularShader();
    const envScene = new RoomEnvironment();
    // sigma=0.02 keeps env detail sharper for crisper specular.
    this.envMap = pmrem.fromScene(envScene, 0.02).texture;
    pmrem.dispose();
  }

  bootstrapStages(): void {
    this.homeBalloons = new HomeBalloons(this.camera);
    void this.homeBalloons.preInit().then(() => {
      this.homeBalloons.init();
      if (this.envMap) this.homeBalloons.scene.environment = this.envMap;
      visuals.stage3DList.push(this.homeBalloons);
    });

    this.homeHeroSection = new HomeHeroSection();
    // Wait one tick so DOM/CSS are ready before SplitType processes
    requestAnimationFrame(() => this.homeHeroSection.init());
  }

  setupScroll(): void {
    const contentDom = document.getElementById("page-container") || document.body;
    const indicator = document.getElementById("scroll-indicator");
    const indicatorBar = document.getElementById("scroll-indicator-bar");
    scrollManager.init({
      contentDom,
      domScrollIndicator: indicator,
      domScrollIndicatorBar: indicatorBar,
    });
    // The visible #home-hero is fixed-position; for FOV scroll calc we need an element
    // inside the virtual-scroll content whose rect actually moves with scroll.
    this.domHomeHero = document.getElementById("home-hero-virtual");
  }

  setupClick(): void {
    const visualContainer =
      document.getElementById("home-hero-visual-container") ||
      document.getElementById("canvas");
    if (!visualContainer) return;
    visualContainer.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;
      if (target.closest("button, a, .pill")) return;
      // Click on a sheet -> fold animation. Click on empty canvas -> color cycle.
      const folded = this.homeBalloons?.triggerFoldAt(e.clientX, e.clientY);
      if (!folded) changeHomeHeroColorSignal.dispatch();
    });
  }

  preloaderRef(): void {
    this.domPreloader = document.getElementById("preloader");
  }

  fadePreloader(): void {
    if (!this.domPreloader || this.domPreloader.dataset.faded === "1") return;
    this.domPreloader.dataset.faded = "1";
    this.domPreloader.style.opacity = "0";
    this.domPreloader.style.pointerEvents = "none";
    setTimeout(() => {
      if (this.domPreloader) this.domPreloader.style.display = "none";
    }, 800);
  }

  resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    properties.width = w;
    properties.height = h;
    properties.viewportWidth = w * properties.dpr;
    properties.viewportHeight = h * properties.dpr;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    for (const stage of visuals.stage3DList) stage.resize(w, h);
  }

  tick(): void {
    const dt = Math.min(this.clock.getDelta(), 1 / 30);
    properties.dt = dt;
    properties.time += dt;

    // Preloader fade after a brief warm-up window
    this.bootCountdown -= dt;
    if (this.bootCountdown <= 0) this.fadePreloader();

    scrollManager.update(dt);
    properties.scrollProgress = Math.max(0, Math.min(1, scrollManager.scrollView));

    // FOV from visible-overlap aspect (issue 11)
    if (this.domHomeHero) {
      const r = scrollManager.getDomRange(this.domHomeHero);
      if (r.isActive && r.height > 0) {
        const aspect = r.width / r.height;
        this.camera.fov = math.fit(aspect, 2.2, 2 / 3, 18, 30);
      } else {
        this.camera.fov = 18;
      }
      this.camera.updateProjectionMatrix();
    }

    if (this.homeHeroSection) this.homeHeroSection.update();

    for (const stage of visuals.stage3DList) {
      if (stage.isActive) {
        stage.update(dt);
        stage.onBeforeRender.dispatch(dt);
        this.renderer.render(stage.scene, this.camera);
        stage.onAfterRender.dispatch(dt);
      }
    }
  }
}
