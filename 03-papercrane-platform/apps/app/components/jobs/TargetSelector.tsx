"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { Plus, ArrowLeft } from "lucide-react";
import type { Target } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { CreateTargetWizard } from "@/components/targets/CreateTargetWizard";

type TargetSelectorProps = {
  targets: Target[];
  selectedId: string | null;
  onSelect: (targetId: string) => void;
  loading?: boolean;
  error?: string;
  projectId?: string;
  onCreationChange?: (creating: boolean) => void;
};

export function TargetSelector({ targets, selectedId, onSelect, loading = false, error, projectId, onCreationChange }: TargetSelectorProps) {
  const selectId = useId();
  const [creating, setCreating] = useState(false);
  const utils = trpc.useUtils();
  const setCreateMode = (value: boolean) => {
    setCreating(value);
    onCreationChange?.(value);
  };
  if (creating) return (
    <section className="max-w-3xl space-y-6" aria-label="Add target to this job">
      <button type="button" onClick={() => setCreateMode(false)} className="inline-flex items-center gap-2 text-sm text-crane">
        <ArrowLeft className="h-4 w-4" /> Back to job inputs
      </button>
      <CreateTargetWizard projectId={projectId} onCreated={async (id) => {
        await utils.targets.list.invalidate();
        onSelect(id);
        setCreateMode(false);
      }} />
    </section>
  );

  if (loading) return <p className="py-5 text-sm text-graphite">Loading targets…</p>;
  const selected = targets.find(t => t.id === selectedId);
  return (
    <div className="max-w-2xl space-y-4">
      {targets.length > 0 ? <>
        <label htmlFor={selectId} className="block text-sm text-graphite">Saved target</label>
        <select id={selectId} value={selectedId ?? ""} onChange={e => onSelect(e.target.value)} aria-invalid={Boolean(error) || undefined} data-testid="e2e-job-target-select" className="w-full rounded-xl bg-paper-fold px-4 py-3 text-base text-ink">
          <option value="" disabled>Choose a target…</option>
          {targets.map(t => <option key={t.id} value={t.id}>{t.name}{t.chain ? ` · Chain ${t.chain}` : ""}</option>)}
        </select>
        {selected && <div className="flex items-center justify-between gap-4 text-sm text-graphite">
          <p>{selected.pdbId || "Uploaded structure"}{selected.chain ? ` · Chain ${selected.chain}` : ""}</p>
          <Link href={`/app/targets/${selected.id}`} target="_blank" rel="noopener noreferrer" className="text-crane">Inspect target ↗</Link>
        </div>}
      </> : <p className="text-sm text-graphite">Add a protein structure to use as your target.</p>}
      <button type="button" onClick={() => setCreateMode(true)} className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 text-sm text-paper hover:bg-crane">
        <Plus className="h-4 w-4" /> Add target
      </button>
      <p className="text-xs text-graphite">Use a PDB ID or upload a structure. You’ll return here when it’s saved.</p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    </div>
  );
}
