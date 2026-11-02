/**
 * Browser-side zip bundling.
 *
 * If `jszip` is bundled in the app deps we dynamically import it and stream a
 * real zip into the user's downloads folder. If it's NOT installed (current
 * default: see Wave-13 owner note), we fall back to triggering individual
 * downloads with a small delay between each so the browser doesn't choke.
 *
 * The fallback is deliberately ugly: it's a stop-gap, not the long-term UX.
 * Once jszip lands in `apps/app/package.json` the dynamic import will start
 * working with no other code changes.
 */

export interface ZipFile {
  /** Filename inside the archive, e.g. "design_42_abc123.cif" */
  name: string;
  /** Remote URL to fetch the file body from. Must be CORS-accessible. */
  url: string;
}

export interface ZipResult {
  /** "zip" if a real archive was produced, "fallback" if we streamed singles */
  mode: "zip" | "fallback";
  /** Number of files actually delivered (i.e. fetched OK). */
  count: number;
  /** Errors collected per-file; non-fatal: we keep going. */
  errors: Array<{ name: string; message: string }>;
}

let jszipPromise: Promise<unknown> | null = null;

async function loadJsZip(): Promise<unknown | null> {
  if (jszipPromise) return jszipPromise;
  jszipPromise = (async () => {
    try {
      // Webpack/Turbopack will treeshake this if jszip is not in deps; the
      // import will throw at runtime. We catch and fall back gracefully.
      const mod = await import(/* webpackIgnore: true */ "jszip" as string);
      return (mod as { default?: unknown }).default ?? mod;
    } catch (err) {
      console.warn(
        "[export/zip] jszip not installed: falling back to individual downloads",
        err,
      );
      return null;
    }
  })();
  return jszipPromise;
}

/** True if jszip is available in this build. */
export async function isZipAvailable(): Promise<boolean> {
  const z = await loadJsZip();
  return z != null;
}

/** Trigger a single download via an anchor tag. Browser-only. */
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke shortly after so the download actually starts first.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** Trigger a download by URL (no fetch: lets the browser stream directly). */
function triggerDownloadByUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // `download` only works cross-origin if the server sends Content-Disposition;
  // for our presigned R2 urls that's already configured.
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export type ZipProgress = (done: number, total: number, name: string) => void;

/**
 * Build a zip from `files` and trigger a single download. If jszip isn't
 * available, fall back to one-by-one downloads with a 250ms gap.
 */
export async function bundleAndDownload(
  files: ZipFile[],
  archiveName: string,
  onProgress?: ZipProgress,
): Promise<ZipResult> {
  const errors: Array<{ name: string; message: string }> = [];
  const JsZipCtor = (await loadJsZip()) as
    | (new () => {
        file: (name: string, data: ArrayBuffer | Blob) => void;
        generateAsync: (opts: { type: "blob" }) => Promise<Blob>;
      })
    | null;

  if (JsZipCtor) {
    const zip = new JsZipCtor();
    let done = 0;
    for (const f of files) {
      try {
        const res = await fetch(f.url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        zip.file(f.name, await res.arrayBuffer());
        done += 1;
        onProgress?.(done, files.length, f.name);
      } catch (err) {
        errors.push({
          name: f.name,
          message: err instanceof Error ? err.message : "fetch failed",
        });
      }
    }
    const blob = await zip.generateAsync({ type: "blob" });
    triggerDownload(blob, archiveName);
    return { mode: "zip", count: done, errors };
  }

  // Fallback: stagger individual downloads.
  let done = 0;
  for (const f of files) {
    try {
      triggerDownloadByUrl(f.url, f.name);
      done += 1;
      onProgress?.(done, files.length, f.name);
      await new Promise((r) => setTimeout(r, 250));
    } catch (err) {
      errors.push({
        name: f.name,
        message: err instanceof Error ? err.message : "download failed",
      });
    }
  }
  return { mode: "fallback", count: done, errors };
}

/** Trigger a download from an in-memory string (FASTA/CSV/JSON). */
export function downloadText(
  text: string,
  filename: string,
  mime = "text/plain;charset=utf-8",
) {
  const blob = new Blob([text], { type: mime });
  triggerDownload(blob, filename);
}
