import { createShader, createSharedDevice } from "shaders/js";
import type { PresetConfig, ShaderInstance } from "shaders/js";

type ShaderSurface = "hero" | "thesis" | "tools" | "cta";

const shaderOrder: ShaderSurface[] = ["hero", "thesis", "tools", "cta"];

const presets: Record<ShaderSurface, PresetConfig> = {
  hero: {
    components: [
      {
        type: "SolidColor",
        id: "hero-base",
        props: { color: "#f7f3eb" },
      },
      {
        type: "MultiPointGradient",
        id: "hero-wash",
        props: {
          colorA: "#f7f3eb",
          positionA: { x: 0.08, y: 0.12 },
          colorB: "#d8e3c9",
          positionB: { x: 0.82, y: 0.18 },
          colorC: "#f0ddbd",
          positionC: { x: 0.2, y: 0.82 },
          colorD: "#c5d2b8",
          positionD: { x: 0.76, y: 0.78 },
          colorE: "#20483b",
          positionE: { x: 0.88, y: 0.56 },
          smoothness: 2.35,
          opacity: 0.46,
          blendMode: "softLight",
        },
      },
      {
        type: "Strands",
        id: "hero-strands",
        props: {
          speed: 0.08,
          amplitude: 0.62,
          frequency: 0.72,
          lineCount: 14,
          lineWidth: 0.035,
          waveColor: "#1f4438",
          pinEdges: true,
          start: { x: -0.08, y: 0.78 },
          end: { x: 1.08, y: 0.32 },
          opacity: 0.13,
          blendMode: "multiply",
        },
      },
      {
        type: "DotGrid",
        id: "hero-grid",
        props: {
          color: "#1f4438",
          density: 86,
          dotSize: 0.11,
          twinkle: 0.08,
          opacity: 0.08,
          blendMode: "multiply",
        },
      },
    ],
  },
  thesis: {
    components: [
      {
        type: "FlowingGradient",
        id: "thesis-flow",
        props: {
          colorA: "#f7f3eb",
          colorB: "#dfe8cf",
          colorC: "#f4dfbb",
          colorD: "#a8bda0",
          colorSpace: "oklch",
          speed: 0.22,
          distortion: 0.5,
          seed: 17,
          opacity: 0.42,
          blendMode: "softLight",
        },
      },
      {
        type: "Strands",
        id: "thesis-strands",
        props: {
          speed: 0.05,
          amplitude: 0.35,
          frequency: 1.1,
          lineCount: 18,
          lineWidth: 0.025,
          waveColor: "#1f4438",
          pinEdges: true,
          start: { x: -0.05, y: 0.72 },
          end: { x: 1.05, y: 0.22 },
          opacity: 0.16,
          blendMode: "multiply",
        },
      },
      {
        type: "DotGrid",
        id: "thesis-grid",
        props: {
          color: "#7a4b1c",
          density: 64,
          dotSize: 0.08,
          twinkle: 0,
          opacity: 0.06,
          blendMode: "multiply",
        },
      },
    ],
  },
  tools: {
    components: [
      {
        type: "SolidColor",
        id: "tools-base",
        props: { color: "#f7f3eb" },
      },
      {
        type: "Voronoi",
        id: "tools-cells",
        props: {
          colorA: "#eef5df",
          colorB: "#f5e4c8",
          colorBorder: "#1f4438",
          scale: 7.5,
          speed: 0.06,
          seed: 29,
          edgeIntensity: 0.18,
          edgeSoftness: 0.018,
          colorSpace: "oklch",
          opacity: 0.16,
          blendMode: "multiply",
        },
      },
      {
        type: "DotGrid",
        id: "tools-grid",
        props: {
          color: "#1f4438",
          density: 54,
          dotSize: 0.09,
          twinkle: 0.18,
          opacity: 0.12,
          blendMode: "multiply",
        },
      },
    ],
  },
  cta: {
    components: [
      {
        type: "SolidColor",
        id: "cta-base",
        props: { color: "#f7f3eb" },
      },
      {
        type: "FlowingGradient",
        id: "cta-flow",
        props: {
          colorA: "#f7f3eb",
          colorB: "#c8d6bb",
          colorC: "#eed5ad",
          colorD: "#21483b",
          colorSpace: "oklch",
          speed: 0.18,
          distortion: 0.42,
          seed: 41,
          opacity: 0.34,
          blendMode: "softLight",
        },
      },
      {
        type: "Beam",
        id: "cta-beam",
        props: {
          startPosition: { x: -0.04, y: 0.88 },
          endPosition: { x: 1.04, y: 0.22 },
          startThickness: 0.52,
          endThickness: 0.18,
          startSoftness: 4.8,
          endSoftness: 5.6,
          insideColor: "#1f4438",
          outsideColor: "#f0d8ad",
          colorSpace: "oklch",
          opacity: 0.16,
          blendMode: "multiply",
        },
      },
      {
        type: "Strands",
        id: "cta-strands",
        props: {
          speed: 0.07,
          amplitude: 0.28,
          frequency: 0.9,
          lineCount: 10,
          lineWidth: 0.03,
          waveColor: "#1f4438",
          pinEdges: true,
          start: { x: 0.08, y: 0.92 },
          end: { x: 0.96, y: 0.12 },
          opacity: 0.1,
          blendMode: "multiply",
        },
      },
    ],
  },
};

let initialized = false;

export function initShaderPolish(): void {
  if (initialized || typeof window === "undefined") return;
  initialized = true;

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    document.body.classList.add("shaders-skipped");
    return;
  }

  const canvases = Array.from(
    document.querySelectorAll<HTMLCanvasElement>("[data-shader-surface]")
  );
  if (!canvases.length) return;

  const schedule = "requestIdleCallback" in window
    ? (callback: () => void) =>
        (
          window as Window & {
            requestIdleCallback: (
              callback: IdleRequestCallback,
              options?: IdleRequestOptions
            ) => number;
          }
        ).requestIdleCallback(() => callback(), { timeout: 1200 })
    : (callback: () => void) => window.setTimeout(callback, 120);

  schedule(() => {
    void startShaders(canvases);
  });
}

async function startShaders(canvases: HTMLCanvasElement[]) {
  const instances: ShaderInstance[] = [];
  const gpu = await createSharedDevice({ powerPreference: "low-power" }).catch(
    () => null
  );

  for (const key of shaderOrder) {
    const canvas = canvases.find((node) => node.dataset.shaderSurface === key);
    if (!canvas) continue;

    try {
      const shader = await createShader(canvas, presets[key], {
        colorSpace: "srgb",
        disableTelemetry: true,
        gpu: gpu ?? undefined,
        onReady: () => canvas.classList.add("is-shader-ready"),
      });
      instances.push(shader);
    } catch (error) {
      canvas.classList.add("is-shader-unavailable");
      if (import.meta.env.DEV) {
        console.warn(`[shader-polish] ${key} surface failed`, error);
      }
    }
  }

  if (!instances.length) {
    document.body.classList.add("shaders-unavailable");
    return;
  }

  document.body.classList.add("shaders-ready");

  document.addEventListener("visibilitychange", () => {
    instances.forEach((shader) => {
      if (document.hidden) shader.pause();
      else shader.resume();
    });
  });

  window.addEventListener(
    "pagehide",
    () => {
      instances.forEach((shader) => shader.destroy());
    },
    { once: true }
  );
}
