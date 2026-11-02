import * as THREE from "three";

/**
 * Procedural paper-grain normal map. Mostly flat (z=255) with low-amplitude
 * red/green channel jitter that reads as paper fiber when sampled by the
 * standard normalMap pipeline.
 */
let cached: THREE.CanvasTexture | null = null;

export function getPaperGrainNormalMap(): THREE.CanvasTexture {
  if (cached) return cached;
  const size = 512;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(size, size);
  // Two-octave value noise: large blobs + fine grain.
  const coarseScale = 24;
  const fineAmp = 14;
  const coarseAmp = 6;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const fineX = (Math.random() - 0.5) * fineAmp;
      const fineY = (Math.random() - 0.5) * fineAmp;
      // Coarse: pseudo-blob via low-frequency lookup
      const cx = (Math.sin(x / coarseScale) + Math.cos(y / coarseScale * 1.3)) * coarseAmp;
      const cy = (Math.cos(x / coarseScale * 1.1) + Math.sin(y / coarseScale)) * coarseAmp;
      img.data[i] = 128 + fineX + cx;
      img.data[i + 1] = 128 + fineY + cy;
      img.data[i + 2] = 255;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2, 2);
  tex.colorSpace = THREE.NoColorSpace;
  cached = tex;
  return tex;
}
