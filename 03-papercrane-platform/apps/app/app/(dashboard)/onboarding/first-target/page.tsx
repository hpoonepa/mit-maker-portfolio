/**
 * Step 3: Create the first target.
 *
 * Three ways in, all landing on the SAME wired pipeline:
 *
 *   1. "Use the example target" (PD-L1, PDB 5O45): one click, zero typing.
 *      This is the demo path and is the visual primary action.
 *   2. Paste an RCSB PDB ID: fetched through our same-origin `/api/pdb/[id]`
 *      proxy (never rcsb.org directly from the browser).
 *   3. Upload a .pdb/.cif from disk.
 *
 * All three end up calling:
 *      trpc.targets.getUploadUrl({ filename, contentLength })
 *   →  PUT the bytes straight to R2 with the presigned URL
 *   →  trpc.targets.createFromUpload({ uploadKey, name, chain? })
 *
 * WHY the PDB-ID path also uploads: `targets.create` writes columns
 * (slug/chain/class/tier/description) that do not exist on the `targets`
 * table and omits the NOT NULL `artifact_key`/`checksum` columns, so it
 * fails at the DB. `createFromUpload` is the procedure that actually
 * persists a row, so we funnel every path through it: the server then
 * parses the structure and derives the PDB id itself.
 *
 * Skippable: users can go straight on without a target. The skip state is
 * persisted so the dashboard can nudge them to finish later.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { StepContainer } from "@/components/onboarding/StepContainer";
import { TargetPresetGrid } from "@/components/onboarding/TargetPresetGrid";
import {
  advance,
  createOnboardingState,
  loadState,
  saveState,
  skip,
  updateTargetDraft,
  type TargetDraft,
} from "@/lib/onboarding/state";
import { PRESET_TARGETS } from "@/lib/onboarding/presetTargets";
import { trpc } from "@/lib/trpc/client";
import { writeClientCache } from "@/lib/onboarding-state";
import { pdbIdSchema, headFetchPdb } from "@/lib/pdb/fetch";
import { uploadStructureFile } from "@/lib/pdb/upload";

// ── The hand-off record read by /onboarding/first-job ───────────────────────
//
// `TargetDraft` in lib/onboarding/state.ts has no room for the real database
// id, so we persist a small companion record alongside it. Kept local to the
// two onboarding pages that use it rather than adding a shared module.

const TARGET_RECORD_KEY = "papercrane.onboarding.target.v1";

interface JobHotspot {
  chain: string;
  residues: number[];
}

interface OnboardingTargetRecord {
  /** UUID of the row created by `targets.createFromUpload`. */
  targetId: string;
  name: string;
  /** 4-char RCSB id when we know it, else null (custom upload). */
  pdbId: string | null;
  /** Single-letter chain the run should design against, when known. */
  chain: string | null;
  hotspots: JobHotspot[];
}

function writeTargetRecord(record: OnboardingTargetRecord): void {
  try {
    if (typeof globalThis.localStorage === "undefined") return;
    globalThis.localStorage.setItem(TARGET_RECORD_KEY, JSON.stringify(record));
  } catch {
    // Private mode / quota: the flow still works, first-job just shows the
    // "no target yet" panel instead of a pre-filled run.
  }
}

// ── The one-click demo target ───────────────────────────────────────────────

const EXAMPLE_TARGET = {
  name: "PD-L1 (example target)",
  pdbId: "5O45",
  chain: "A",
  /**
   * PD-L1 IgV-domain interface residues, same set the built-in PD-L1 preset
   * uses. Written as chain+residue tokens so they read like the rest of the
   * app, parsed into the `{chain, residues[]}` shape the job API wants.
   */
  hotspotTokens: ["A54", "A56", "A115", "A123"],
} as const;

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // matches the server-side cap
const ALLOWED_EXT_RE = /\.(pdb|ent|cif|mmcif)$/i;

/** "A54" → merged into `[{ chain: "A", residues: [54, ...] }]`. */
function parseHotspotTokens(tokens: readonly string[]): JobHotspot[] {
  const byChain = new Map<string, number[]>();
  for (const token of tokens) {
    const match = /^([A-Za-z])(\d+)$/.exec(token.trim());
    if (!match) continue;
    const chain = (match[1] ?? "").toUpperCase();
    const residue = Number.parseInt(match[2] ?? "", 10);
    if (!chain || !Number.isInteger(residue)) continue;
    const residues = byChain.get(chain) ?? [];
    if (!residues.includes(residue)) residues.push(residue);
    byChain.set(chain, residues);
  }
  return Array.from(byChain, ([chain, residues]) => ({ chain, residues }));
}

/**
 * The server validates upload filenames against a tight character class and
 * an extension allowlist. Normalise here so a file called `my structure
 * (final)#2.pdb` doesn't bounce off a 400 the user can't act on.
 */
function safeUploadFilename(original: string): string {
  const extMatch = ALLOWED_EXT_RE.exec(original);
  const ext = (extMatch?.[0] ?? ".pdb").toLowerCase();
  const stem = original
    .slice(0, original.length - (extMatch?.[0].length ?? 0))
    .replace(/[^A-Za-z0-9._()+~\- ]/g, "-")
    .replace(/^[^A-Za-z0-9]+/, "")
    .slice(0, 90);
  return `${stem || "structure"}${ext}`;
}

function humanError(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message.trim() : "";
  if (!raw) return fallback;
  if (/upload/i.test(raw)) {
    return "We downloaded the structure, but couldn't save it to your workspace. Try again in a moment.";
  }
  if (/not_found|not found|\b404\b/i.test(raw)) {
    return "We couldn't find that structure in the RCSB PDB. Check the 4-character ID (for example 5O45) and try again.";
  }
  if (/network|timed out|upstream/i.test(raw)) {
    return "We couldn't reach the structure database just now. Check your connection and try again.";
  }
  if (/UNAUTHORIZED|not signed in/i.test(raw)) {
    return "Your session expired. Reload the page and sign in again.";
  }
  return raw;
}

type Phase = "idle" | "fetching" | "uploading" | "saving" | "done";

export default function FirstTargetPage() {
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [activePath, setActivePath] = useState<
    "example" | "pdb" | "upload" | null
  >(null);

  const [pdbInput, setPdbInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);

  const setStep = trpc.onboarding.setStep.useMutation();
  const getUploadUrl = trpc.targets.getUploadUrl.useMutation();
  const createFromUpload = trpc.targets.createFromUpload.useMutation();

  const busy = phase === "fetching" || phase === "uploading" || phase === "saving";

  useEffect(() => {
    const s = loadState();
    if (s?.targetDraft?.source === "preset") setPdbInput(s.targetDraft.pdbId);
  }, []);

  async function persistAndGo(nextHref: string) {
    writeClientCache({ step: "first-job", persona: null });
    try {
      await setStep.mutateAsync({ step: "first-job" });
    } catch {
      // ignore: localStorage carries the draft
    }
    router.push(nextHref);
  }

  /**
   * The single wired pipeline: presign → PUT → server-side parse + persist,
   * then hand the new target id to the first-job step.
   */
  async function uploadAndCreate(args: {
    file: File;
    name: string;
    pdbId: string | null;
    chain: string | null;
    hotspots: JobHotspot[];
    draft: TargetDraft;
  }) {
    if (args.file.size > MAX_UPLOAD_BYTES) {
      throw new Error(
        "That structure is larger than 10 MB. Try a single chain or a smaller entry.",
      );
    }

    setPhase("uploading");
    setProgress(0);
    const { uploadKey } = await uploadStructureFile({
      file: args.file,
      getSignedUrl: async ({ filename, contentLength }) => {
        const out = await getUploadUrl.mutateAsync({ filename, contentLength });
        return { url: out.url, uploadKey: out.uploadKey };
      },
      onProgress: setProgress,
    });

    setPhase("saving");
    const result = await createFromUpload.mutateAsync({
      uploadKey,
      name: args.name,
      chain: args.chain ?? undefined,
    });
    const created = result.target as { id: string; pdbId?: string | null };

    writeTargetRecord({
      targetId: created.id,
      name: args.name,
      pdbId: args.pdbId ?? created.pdbId ?? null,
      chain: args.chain,
      hotspots: args.hotspots,
    });

    const base = loadState() ?? createOnboardingState();
    saveState(
      advance(updateTargetDraft({ ...base, step: "first-target" }, args.draft)),
    );

    setPhase("done");
    await persistAndGo("/onboarding/first-job");
  }

  /** Fetch a structure by RCSB id through our proxy, then create the target. */
  async function createFromPdbId(args: {
    pdbId: string;
    name: string;
    chain: string | null;
    hotspots: JobHotspot[];
    presetId?: string;
  }) {
    const parsed = pdbIdSchema.safeParse(args.pdbId);
    if (!parsed.success) {
      throw new Error(
        parsed.error.issues[0]?.message ??
          "That doesn't look like a PDB ID. They look like 5O45.",
      );
    }
    const id = parsed.data;

    setPhase("fetching");
    // Resolves .cif → .pdb with retries and surfaces typo'd IDs as 404s.
    const resolved = await headFetchPdb(id, "auto");
    const res = await fetch(resolved.url);
    if (!res.ok) {
      throw new Error(
        res.status === 404
          ? "not_found"
          : `Could not download ${id} from the RCSB PDB (status ${res.status}).`,
      );
    }
    const blob = await res.blob();
    const ext = resolved.format === "cif" ? "cif" : "pdb";

    await uploadAndCreate({
      file: new File([blob], `${id}.${ext}`, { type: "chemical/x-pdb" }),
      name: args.name,
      pdbId: id,
      chain: args.chain,
      hotspots: args.hotspots,
      draft: {
        source: "preset",
        presetId: args.presetId ?? id.toLowerCase(),
        pdbId: id,
      },
    });
  }

  /** Shared guard so no button can ever fail silently. */
  async function run(
    path: "example" | "pdb" | "upload",
    fallback: string,
    fn: () => Promise<void>,
  ) {
    if (busy) return;
    setError(null);
    setActivePath(path);
    try {
      await fn();
    } catch (err) {
      setPhase("idle");
      setProgress(0);
      setActivePath(null);
      setError(humanError(err, fallback));
    }
  }

  function handleExample() {
    void run("example", "We couldn't set up the example target.", () =>
      createFromPdbId({
        pdbId: EXAMPLE_TARGET.pdbId,
        name: EXAMPLE_TARGET.name,
        chain: EXAMPLE_TARGET.chain,
        hotspots: parseHotspotTokens(EXAMPLE_TARGET.hotspotTokens),
        presetId: "pdl1",
      }),
    );
  }

  function handlePdbId() {
    const typed = pdbInput.trim().toUpperCase();
    // If the id matches one of the built-in presets, carry its curated chain
    // and hotspots through instead of submitting a bare structure.
    const preset = PRESET_TARGETS.find((p) => p.pdbId.toUpperCase() === typed);
    void run("pdb", "We couldn't create that target.", () =>
      createFromPdbId({
        pdbId: typed,
        name: preset?.name ?? `PDB ${typed}`,
        chain: preset?.chain ?? null,
        hotspots: preset ? parseHotspotTokens(preset.hotspots) : [],
        presetId: preset?.id,
      }),
    );
  }

  function handleUpload() {
    const picked = file;
    if (!picked) return;
    void run("upload", "We couldn't upload that file.", () => {
      const stem = picked.name.replace(ALLOWED_EXT_RE, "");
      return uploadAndCreate({
        file: new File([picked], safeUploadFilename(picked.name), {
          type: "chemical/x-pdb",
        }),
        name: stem.length >= 2 ? stem.slice(0, 200) : "Uploaded target",
        pdbId: null,
        chain: null,
        hotspots: [],
        draft: { source: "upload", fileName: picked.name },
      });
    });
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    setError(null);
    if (!picked) {
      setFile(null);
      return;
    }
    if (!ALLOWED_EXT_RE.test(picked.name)) {
      setFile(null);
      setError("Please pick a .pdb, .ent, .cif or .mmcif file.");
      return;
    }
    if (picked.size > MAX_UPLOAD_BYTES) {
      setFile(null);
      setError("That file is larger than 10 MB. Try a single chain instead.");
      return;
    }
    setFile(picked);
  }

  async function handleSkip() {
    if (busy) return;
    const base = loadState() ?? createOnboardingState();
    saveState(skip({ ...base, step: "first-target" }));
    await persistAndGo("/onboarding/first-job");
  }

  const statusLine =
    phase === "fetching"
      ? "Fetching the structure from the PDB…"
      : phase === "uploading"
        ? `Saving the structure to your workspace… ${progress}%`
        : phase === "saving"
          ? "Reading the chains and residues…"
          : phase === "done"
            ? "Target created. Setting up your first run…"
            : null;

  const pdbIdLooksValid = pdbIdSchema.safeParse(pdbInput).success;

  return (
    <StepContainer
      eyebrow="Step 03 / Target"
      title="Pick your first target"
      subtitle="A target is the protein you want to design a binder against: the thing your new molecule has to stick to."
      secondary={{ label: "Back", href: "/onboarding/create-org" }}
      skip={{ label: "Skip for now", onClick: handleSkip, disabled: busy }}
    >
      {/* ── Primary: the one-click demo path ─────────────────────────────── */}
      <section
        data-testid="example-target"
        className="rounded-lg border-2 border-crane bg-paper p-6"
      >
        <p className="font-sans text-[0.66rem] text-crane">
          Recommended · fastest way to see it work
        </p>
        <h2 className="mt-2 font-display text-2xl leading-tight text-ink">
          Use the example target
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-graphite">
          <span className="text-ink">PD-L1</span>: a protein on the surface of
          many tumour cells that switches off the immune system. It is the most
          studied target in this field, so it&rsquo;s an honest first run. We
          load the published 3D structure{" "}
          <span className="font-mono text-crane-deep">
            PDB {EXAMPLE_TARGET.pdbId}
          </span>{" "}
          and pre-mark the spots a binder should touch. No typing needed.
        </p>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {EXAMPLE_TARGET.hotspotTokens.map((token) => (
            <span
              key={token}
              className="rounded-full border border-lattice bg-paper-fold/60 px-2 py-0.5 font-mono text-[0.68rem] text-ink-soft"
            >
              {token}
            </span>
          ))}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-graphite-soft">
          Those chips are <span className="text-graphite">hotspots</span>: the
          exact spots on the target&rsquo;s surface we ask the designer to aim
          at. &ldquo;A54&rdquo; means residue 54 on chain A.
        </p>

        <button
          type="button"
          onClick={handleExample}
          disabled={busy}
          data-testid="use-example-target"
          className="mt-5 inline-flex w-full items-center justify-center rounded-full bg-crane px-6 py-3 text-sm font-medium text-paper transition-all hover:bg-crane-deep disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy && activePath === "example"
            ? "Setting up PD-L1…"
            : "Use the example target (PD-L1)"}
        </button>
      </section>

      {statusLine && (
        <p
          data-testid="target-status"
          role="status"
          className="text-sm text-graphite"
        >
          {statusLine}
        </p>
      )}

      {error && (
        <p
          data-testid="target-error"
          role="alert"
          className="rounded-xl border border-crane/40 bg-crane-glow/40 px-4 py-3 text-sm text-crane-deep"
        >
          {error}
        </p>
      )}

      {/* ── Secondary: bring your own ────────────────────────────────────── */}
      <div className="pt-6">
        <h2 className="font-sans text-[0.66rem] text-graphite">
          Or bring your own target
        </h2>
        <p className="mt-2 text-xs leading-relaxed text-graphite-soft">
          Everything below is optional. You can add targets later from the
          Targets page.
        </p>
      </div>

      <section>
        <label className="block">
          <span className="mb-2 block text-sm text-ink">
            Paste a PDB ID
            <span className="ml-2 text-xs text-graphite-soft">
              a 4-character code for a published 3D structure, e.g. 5O45
            </span>
          </span>
          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              value={pdbInput}
              onChange={(e) => {
                setPdbInput(e.target.value);
                if (error) setError(null);
              }}
              placeholder="5O45"
              autoComplete="off"
              spellCheck={false}
              maxLength={12}
              data-testid="pdb-id-input"
              className="min-w-0 flex-1 rounded-xl border border-lattice bg-paper px-4 py-3 font-mono text-sm uppercase text-ink placeholder:text-graphite-soft focus:border-crane focus:outline-none focus:ring-2 focus:ring-crane-glow"
            />
            <button
              type="button"
              onClick={handlePdbId}
              disabled={busy || !pdbIdLooksValid}
              data-testid="create-from-pdb-id"
              className="inline-flex items-center justify-center rounded-full border border-lattice-strong px-6 py-3 text-sm font-medium text-ink transition-all hover:bg-paper-fold disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy && activePath === "pdb" ? "Fetching…" : "Fetch & create"}
            </button>
          </div>
          {pdbInput.length > 0 && !pdbIdLooksValid && (
            <p className="mt-2 text-xs text-graphite">
              PDB IDs are 4 characters starting with a digit, like 5O45 or 6M0J.
            </p>
          )}
        </label>
      </section>

      <section>
        <h3 className="mb-3 text-sm text-ink">Or upload your own structure</h3>
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-lattice-strong bg-paper-fold/40 py-8 text-center transition-colors hover:bg-paper-fold">
          <input
            type="file"
            accept=".pdb,.ent,.cif,.mmcif"
            onChange={handleFileChange}
            disabled={busy}
            data-testid="target-file-input"
            className="hidden"
          />
          <span className="font-display text-lg text-ink">
            {file?.name ?? "Choose a .pdb or .cif file"}
          </span>
          <span className="text-xs text-graphite">
            Max 10 MB · your structures stay private to your workspace
          </span>
        </label>
        {file && (
          <button
            type="button"
            onClick={handleUpload}
            disabled={busy}
            data-testid="create-from-upload"
            className="mt-3 inline-flex items-center justify-center rounded-full border border-lattice-strong px-6 py-2.5 text-sm font-medium text-ink transition-all hover:bg-paper-fold disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy && activePath === "upload"
              ? `Uploading… ${progress}%`
              : `Create target from ${file.name}`}
          </button>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm text-ink">
          Or start from another well-studied target
        </h3>
        <TargetPresetGrid
          selectedId={selectedPresetId}
          onSelect={(p) => {
            setSelectedPresetId(p.id);
            setPdbInput(p.pdbId);
            setError(null);
          }}
        />
        {selectedPresetId && (
          <p className="mt-3 text-xs text-graphite">
            Loaded <span className="font-mono text-ink">{pdbInput}</span> into
            the PDB ID box above: press &ldquo;Fetch &amp; create&rdquo; to use
            it.
          </p>
        )}
      </section>
    </StepContainer>
  );
}
