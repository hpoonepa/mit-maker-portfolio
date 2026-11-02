"use client";

import { ArrowRight, Check } from "lucide-react";
import {
  PAPERCRANE_WORKFLOWS,
  type WorkflowId,
} from "@papercrane/types";
import { cn } from "@/lib/utils";

interface WorkflowPickerProps {
  selectedId: WorkflowId | null;
  availableIds: ReadonlySet<WorkflowId>;
  onSelect: (id: WorkflowId) => void;
}

export function WorkflowPicker({
  selectedId,
  availableIds,
  onSelect,
}: WorkflowPickerProps) {
  return (
    <section aria-labelledby="workflow-heading">
      <div className="flex items-start gap-3">
        <div>
          <h3 id="workflow-heading" className="font-display text-[17px] text-ink">
            Workflows
          </h3>
          <p className="mt-1 font-sans text-[13px] text-graphite">
            Choose a sequence of tools to run together.
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        {PAPERCRANE_WORKFLOWS.map((workflow) => {
          const selected = selectedId === workflow.id;
          const available = availableIds.has(workflow.id);
          return (
            <button
              key={workflow.id}
              type="button"
              disabled={!available}
              aria-pressed={selected}
              onClick={() => onSelect(workflow.id)}
              className={cn(
                "relative rounded-lg p-4 text-left transition-colors",
                selected
                  ? "bg-crane-glow"
                  : "bg-transparent hover:bg-paper-fold/40",
                !available && "cursor-not-allowed opacity-45",
              )}
            >
              {selected && (
                <span className="absolute right-3 top-3 rounded-full bg-crane p-1 text-paper">
                  <Check className="h-3 w-3" aria-hidden="true" />
                </span>
              )}
              <p className="pr-7 font-display text-[15px] text-ink">{workflow.name}</p>
              <p className="mt-1 font-sans text-[12px] leading-relaxed text-graphite">
                {workflow.description}
              </p>
              <ol className="mt-3 flex flex-wrap items-center gap-1.5" aria-label="Workflow stages">
                {workflow.stages.map((stage, index) => (
                  <li key={`${workflow.id}-${stage.toolId}`} className="flex items-center gap-1.5">
                    {index > 0 && <ArrowRight className="h-3 w-3 text-graphite-soft" aria-hidden="true" />}
                    <span className="py-0.5 font-sans text-[12px] text-graphite">
                      {stage.toolId}
                    </span>
                  </li>
                ))}
              </ol>
              {!available && (
                <p className="mt-2 font-sans text-[11px] text-crane-deep">
                  One or more stages are unavailable on this account.
                </p>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
