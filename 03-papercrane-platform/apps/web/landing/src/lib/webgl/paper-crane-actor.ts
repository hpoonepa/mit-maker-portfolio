import * as THREE from "three";
import { clone as cloneSkeleton } from "three/examples/jsm/utils/SkeletonUtils.js";

export type CraneActorOptions = {
  color: THREE.ColorRepresentation;
  grain: THREE.Texture;
  scale: number;
  seed: number;
  featured: boolean;
  colored: boolean;
};

/**
 * A self-contained, articulated paper-crane actor. The stage owns translation
 * and collision; this component owns its material, skeleton pose, silhouette,
 * and small flight gestures.
 */
export class PaperCraneActor {
  readonly root = new THREE.Group();
  readonly model = new THREE.Group();
  readonly material: THREE.MeshPhysicalMaterial;
  readonly mixer: THREE.AnimationMixer | null;
  readonly action: THREE.AnimationAction | null;
  readonly colored: boolean;

  private readonly phase: number;
  private readonly speed: number;
  private readonly bank: number;
  private readonly featured: boolean;
  private readonly baseScale: number;
  private readonly clipDuration: number;

  constructor(
    source: THREE.Object3D,
    clip: THREE.AnimationClip | undefined,
    options: CraneActorOptions,
  ) {
    this.phase = options.seed * Math.PI * 2;
    this.speed = 0.72 + ((options.seed * 17.31) % 1) * 0.55;
    this.bank = (((options.seed * 31.7) % 1) - 0.5) * 0.22;
    this.featured = options.featured;
    this.baseScale = options.scale;
    this.colored = options.colored;

    this.material = createPaperMaterial(options.color, options.grain, options.seed);

    const crane = cloneSkeleton(source);
    crane.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.material = this.material;
      object.castShadow = false;
      object.receiveShadow = false;
      object.frustumCulled = false;
    });

    this.model.add(crane);
    this.root.add(this.model);
    this.root.scale.setScalar(this.baseScale);

    if (clip) {
      this.mixer = new THREE.AnimationMixer(crane);
      this.action = this.mixer.clipAction(clip);
      this.action.play();
      this.action.timeScale = 0;
      this.clipDuration = clip.duration;
    } else {
      this.mixer = null;
      this.action = null;
      this.clipDuration = 0;
    }
  }

  setColor(color: THREE.ColorRepresentation): void {
    this.material.color.set(color);
    this.material.sheenColor.set(color).lerp(new THREE.Color("#f8f0dc"), 0.55);
  }

  update(time: number, depth: number, reducedMotion: boolean): void {
    if (reducedMotion) {
      this.model.rotation.set(0, this.bank, 0);
      this.root.scale.setScalar(this.baseScale);
      this.setFoldPose(0.025);
      return;
    }

    // A quiet wing-breath from the real skeletal unfold animation. A few
    // featured cranes occasionally open farther, creating independent events
    // instead of a synchronized particle loop.
    const breath = 0.022 + Math.sin(time * this.speed + this.phase) * 0.014;
    const eventWave = Math.max(0, Math.sin(time * 0.24 * this.speed + this.phase));
    const event = this.featured ? Math.pow(eventWave, 12) * 0.24 : 0;
    this.setFoldPose(THREE.MathUtils.clamp(breath + event, 0, 0.32));

    const depthDrift = THREE.MathUtils.clamp(depth / 3.5, -1, 1);
    this.model.rotation.x = Math.sin(time * 0.29 * this.speed + this.phase) * 0.055;
    this.model.rotation.y = this.bank + Math.cos(time * 0.21 + this.phase) * 0.075;
    this.model.rotation.z =
      Math.sin(time * 0.38 * this.speed + this.phase * 0.7) * 0.085 - depthDrift * 0.05;

    const pulse = 1 + Math.sin(time * 0.47 + this.phase) * 0.018;
    this.root.scale.setScalar(this.baseScale * pulse);
  }

  private setFoldPose(amount: number): void {
    if (!this.action || !this.mixer || this.clipDuration <= 0) return;
    this.action.time = this.clipDuration * amount;
    this.mixer.update(0);
  }
}

function createPaperMaterial(
  color: THREE.ColorRepresentation,
  grain: THREE.Texture,
  seed: number,
): THREE.MeshPhysicalMaterial {
  const base = new THREE.Color(color);
  const material = new THREE.MeshPhysicalMaterial({
    color: base,
    metalness: 0,
    roughness: 0.76 + (seed % 0.12),
    envMapIntensity: 0.58,
    clearcoat: 0.035,
    clearcoatRoughness: 0.9,
    sheen: 0.22,
    sheenRoughness: 0.86,
    sheenColor: base.clone().lerp(new THREE.Color("#f8f0dc"), 0.55),
    ior: 1.46,
    side: THREE.DoubleSide,
    flatShading: true,
    normalMap: grain,
    normalScale: new THREE.Vector2(0.48, 0.48),
  });

  // The normal map provides fibers in the light; this tiny diffuse variation
  // keeps those fibers visible on faces turned away from the key light.
  material.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <map_fragment>",
      `#include <map_fragment>
      #ifdef USE_NORMALMAP
        float paperFiber = sin(vNormalMapUv.y * 1180.0 + sin(vNormalMapUv.x * 97.0) * 3.0);
        float paperPulp = sin(vNormalMapUv.x * 231.0) * sin(vNormalMapUv.y * 173.0);
        diffuseColor.rgb *= 0.985 + paperFiber * 0.008 + paperPulp * 0.007;
      #endif`,
    );
  };
  material.customProgramCacheKey = () => "paper-crane-fiber-v1";
  return material;
}
