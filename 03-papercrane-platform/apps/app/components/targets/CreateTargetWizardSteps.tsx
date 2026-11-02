"use client";

import { Database, FileText, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChainEntry } from "@/lib/pdb/parse";
import {
  PdbDropZone,
  type PdbDropZonePayload,
} from "@/components/upload/PdbDropZone";
import {
  PdbUploadProgress,
  type UploadPhase,
} from "@/components/upload/PdbUploadProgress";
import { ChainSelector } from "@/components/targets/ChainSelector";
import { EXAMPLE_JOB } from "@/lib/jobs/exampleJob";

export type Source = "rcsb" | "upload" | "sequence";

/**
 * Step bodies for {@link CreateTargetWizard}, split out so the wizard file
 * stays focused on state and submission. Every step leads with a
 * plain-language header: a first-time viewer must never meet an undefined
 * term like "target" or "chain".
 */

function StepHeader({
  title,
  sub,
  ifSkipped,
}: {
  title: string;
  sub: string;
  ifSkipped?: string;
}) {
  return (
    <div className="space-y-1.5">
      <h2 className="font-display text-[20px] tracking-tight text-ink">
        {title}
      </h2>
      <p className="max-w-2xl font-sans text-[13px] leading-relaxed text-graphite">
        {sub}
      </p>
      {ifSkipped && (
        <p className="max-w-2xl font-sans text-[12.5px] leading-relaxed text-graphite-soft">
          <span className="text-[11px] uppercase tracking-[0.12em]">
            If you skip this:
          </span>{" "}
          {ifSkipped}
        </p>
      )}
    </div>
  );
}

// ── Step 1: source picker ─────────────────────────────────────────────────

export function Step1(props: {
  source: Source;
  setSource: (s: Source) => void;
  payload: PdbDropZonePayload | null;
  onAccepted: (p: PdbDropZonePayload) => void;
  pdbId: string;
  setPdbId: (s: string) => void;
  sequence: string;
  setSequence: (s: string) => void;
  /** Friendly validation message for the typed PDB ID, if any. */
  pdbError?: string | null;
  /** Fills in the known-good example (PD-L1 · 5O45) with one click. */
  onUseExample: () => void;
}) {
  const { source, setSource } = props;
  return (
    <div className="space-y-5">
      <StepHeader
        title="Add a protein structure"
        sub="Enter a PDB ID from RCSB, or upload your own PDB or mmCIF file."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SourceCard
          label="RCSB by ID"
          icon={<Database className="w-4 h-4" />}
          active={source === "rcsb"}
          onClick={() => setSource("rcsb")}
          desc="Fetch a published structure straight from RCSB."
        />
        <SourceCard
          label="Upload file"
          icon={<FileText className="w-4 h-4" />}
          active={source === "upload"}
          onClick={() => setSource("upload")}
          desc="Drop a .pdb or .cif from your machine."
        />
      </div>

      <div className="p-6">
        {source === "upload" && <PdbDropZone onAccepted={props.onAccepted} />}
        {source === "rcsb" && (
          <div className="space-y-3">
            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-[12px] text-graphite-soft">
                PDB ID
              </span>
              <input
                type="text"
                value={props.pdbId}
                onChange={(e) => props.setPdbId(e.target.value.toUpperCase())}
                placeholder={EXAMPLE_JOB.targetPdb}
                maxLength={12}
                aria-invalid={props.pdbError ? true : undefined}
                data-testid="e2e-target-pdb-id"
                className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-mono text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
              />
              <span className="font-sans text-[12px] text-graphite">
                Four characters, starting with a digit: it&apos;s printed on
                every RCSB entry page.
              </span>
            </label>

            {props.pdbError && (
              <p
                role="alert"
                data-testid="e2e-target-pdb-error"
                className="font-sans text-[13px] leading-relaxed text-crane-deep"
              >
                {props.pdbError}
              </p>
            )}

            <button
              type="button"
              onClick={props.onUseExample}
              data-testid="e2e-target-use-example"
              className="inline-flex items-center gap-2 rounded-xl border border-crane/40 bg-crane/5 px-4 py-2.5 font-sans text-[13px] text-crane-deep transition-colors hover:bg-crane/10"
            >
              Use example: {EXAMPLE_JOB.targetName} ({EXAMPLE_JOB.targetPdb})
            </button>
          </div>
        )}
        {source === "sequence" && (
          <div className="space-y-3">
            <p className="font-sans text-[13px] leading-relaxed text-graphite">
              Starting from a raw sequence needs a structure-prediction step we
              haven&apos;t switched on yet, so this can&apos;t be saved as a
              target. Use an RCSB ID or upload a structure file instead.
            </p>
            <label className="flex flex-col gap-1.5 opacity-60">
              <span className="font-sans text-[12px] text-graphite-soft">
                Sequence (preview only)
              </span>
              <textarea
                value={props.sequence}
                onChange={(e) => props.setSequence(e.target.value)}
                rows={5}
                disabled
                placeholder=">target&#10;MKLLVL..."
                className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
              />
            </label>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Step 2: configure ─────────────────────────────────────────────────────

interface ProjectListItem {
  id: string;
  name: string;
}

export function Step2(props: {
  source: Source;
  name: string;
  setName: (s: string) => void;
  chain: string;
  setChain: (s: string) => void;
  parsedChains: ChainEntry[];
  projects: unknown[];
  selectedProjectId: string;
  setSelectedProjectId: (s: string) => void;
  /** Friendly validation message for the name, if any. */
  nameError?: string | null;
}) {
  const projects = (props.projects as ProjectListItem[]).filter(
    (p) => typeof p.id === "string" && typeof p.name === "string",
  );
  return (
    <div className="space-y-5">
      <StepHeader
        title="Target details"
        sub="Give it a name, choose the chain, and optionally add it to a project."
      />
      <div className="space-y-5 p-6">
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Name
          </span>
          <input
            type="text"
            required
            maxLength={80}
            value={props.name}
            onChange={(e) => props.setName(e.target.value)}
            placeholder="PD-L1 (5O45)"
            aria-invalid={props.nameError ? true : undefined}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
          {props.nameError && (
            <span
              role="alert"
              className="font-sans text-[12.5px] text-crane-deep"
            >
              {props.nameError}
            </span>
          )}
        </label>

        {props.source === "upload" && props.parsedChains.length > 1 && (
          <ChainSelector
            chains={props.parsedChains}
            value={props.chain}
            onChange={props.setChain}
          />
        )}

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Project (optional)
          </span>
          <select
            value={props.selectedProjectId}
            onChange={(e) => props.setSelectedProjectId(e.target.value)}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[14px] text-ink focus:border-ink focus:outline-none"
          >
            <option value="">No project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

// ── Step 3: confirm ───────────────────────────────────────────────────────

// Exported for regression testing of the error-banner visibility (see
// CreateTargetWizard.test.tsx).
export function Step3(props: {
  source: Source;
  name: string;
  pdbId: string;
  chain: string;
  chosenChainSeq: string;
  chosenChainResidues: number;
  payloadFilename: string;
  payloadSize: number;
  phase: UploadPhase;
  submitError: string | null;
}) {
  return (
    <div className="space-y-5">
      <StepHeader
        title="Save target"
        sub="Save this structure to your workspace."
      />
      <div className="space-y-4 p-6">
        <SummaryRow label="Source" value={sourceLabel(props.source)} />
        <SummaryRow label="Name" value={props.name || "(unnamed)"} />
        {props.source === "rcsb" && (
          <SummaryRow
            label="PDB ID"
            value={props.pdbId.toUpperCase() || "N/A"}
          />
        )}
        {props.source === "upload" && (
          <>
            <SummaryRow label="Chain" value={props.chain || "(auto)"} />
            <SummaryRow
              label="Residues"
              value={String(props.chosenChainResidues)}
            />
            <SummaryRow label="File" value={props.payloadFilename} />
          </>
        )}

        {props.chosenChainSeq && (
          <div className="bg-paper px-4 py-3">
            <p className="font-sans text-[12px] text-graphite-soft">
              Sequence preview: chain {props.chain}
            </p>
            <p className="mt-1 break-all font-mono text-[12px] text-graphite">
              {props.chosenChainSeq.slice(0, 120)}
              {props.chosenChainSeq.length > 120 && "…"}
            </p>
          </div>
        )}

        {props.source === "upload" && props.phase.phase !== "idle" && (
          <PdbUploadProgress
            filename={props.payloadFilename}
            sizeBytes={props.payloadSize}
            status={props.phase}
          />
        )}

        {props.submitError &&
          // Show the error banner whenever a submit error is set: EXCEPT when
          // the upload-progress component (upload source only) is already
          // rendering it, to avoid double display. For RCSB/non-upload sources
          // this is the ONLY place errors surface, so it must render on the
          // "error" phase too.
          !(props.source === "upload" && props.phase.phase === "error") && (
            <p
              role="alert"
              className="rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
            >
              {props.submitError}
            </p>
          )}
      </div>
    </div>
  );
}

// ── Building blocks ───────────────────────────────────────────────────────

export function Stepper({ step }: { step: 1 | 2 | 3 }) {
  const steps = [
    { n: 1, label: "Source" },
    { n: 2, label: "Configure" },
    { n: 3, label: "Confirm" },
  ] as const;
  return (
    <ol className="flex items-center gap-3">
      {steps.map((s, i) => {
        const active = s.n === step;
        const done = s.n < step;
        return (
          <li key={s.n} className="flex items-center gap-3">
            <div
              className={cn(
                "inline-flex h-7 w-7 items-center justify-center rounded-full border font-mono text-[12px]",
                done
                  ? "border-ink bg-ink text-paper"
                  : active
                    ? "border-ink bg-paper text-ink"
                    : "border-lattice bg-paper text-graphite-soft",
              )}
            >
              {done ? <CheckCircle2 className="w-3.5 h-3.5" /> : s.n}
            </div>
            <span
              className={cn(
                "font-sans text-[13px]",
                active ? "text-ink" : "text-graphite",
              )}
            >
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <span className="ml-1 mr-1 h-px w-8 bg-lattice" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function SourceCard(props: {
  label: string;
  icon: React.ReactNode;
  desc: string;
  active: boolean;
  onClick: () => void;
  /** Renders the card as an honest, inert "coming soon" option. */
  comingSoon?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={cn(
        "flex flex-col items-start gap-2 rounded-lg border px-4 py-4 text-left transition-colors",
        props.active
          ? "border-ink bg-paper"
          : "border-lattice bg-paper-fold/30 hover:border-ink/60 hover:bg-paper",
        props.comingSoon && "opacity-70",
      )}
    >
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-lattice bg-paper text-ink">
        {props.icon}
      </span>
      <span className="flex items-center gap-2">
        <span className="font-display text-[16px] text-ink">{props.label}</span>
        {props.comingSoon && (
          <span className="rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-sans text-[9px] text-amber-700">
            Soon
          </span>
        )}
      </span>
      <span className="font-sans text-[12px] text-graphite">{props.desc}</span>
    </button>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="font-sans text-[12px] text-graphite-soft">
        {label}
      </span>
      <span className="font-mono text-[13px] text-ink">{value}</span>
    </div>
  );
}

function sourceLabel(s: Source): string {
  return s === "rcsb"
    ? "RCSB by ID"
    : s === "upload"
      ? "Uploaded file"
      : "Pasted sequence";
}
