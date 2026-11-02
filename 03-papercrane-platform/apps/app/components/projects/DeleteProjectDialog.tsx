"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2, X, AlertTriangle } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";

export interface DeleteProjectDialogProps {
  open: boolean;
  projectId: string;
  projectName: string;
  /** Where to navigate after a successful delete. Defaults to /app/projects. */
  redirectTo?: string;
  onClose: () => void;
}

/**
 * Destructive-confirmation dialog for `projects.delete`.
 *
 * The mutation cascades to Targets, Jobs, and Designs at the DB level
 * (`onDelete: Cascade` on each FK in `schema.prisma`), so we don't need a
 * second-stage confirmation for child rows: Postgres tears them down
 * atomically. We still gate behind a name-typing check because the blast
 * radius is "every job and design ever submitted to this project", which
 * is exactly the kind of click that warrants friction.
 */
export function DeleteProjectDialog({
  open,
  projectId,
  projectName,
  redirectTo = "/app/projects",
  onClose,
}: DeleteProjectDialogProps) {
  const router = useRouter();
  const utils = trpc.useUtils();
  const { toast } = useToast();
  const [confirmText, setConfirmText] = useState("");
  const [topError, setTopError] = useState<string | null>(null);

  const remove = trpc.projects.delete.useMutation({
    onSuccess: () => {
      toast({
        title: "Project deleted",
        description: `“${projectName}” and all of its jobs were removed.`,
        variant: "success",
      });
      // Invalidate list-side caches so the next page render reflects
      // the deletion immediately.
      void utils.projects.list.invalidate();
      void utils.jobs.list.invalidate();
      onClose();
      router.push(redirectTo);
    },
    onError: (err) => {
      setTopError(err.message ?? "Could not delete project.");
    },
  });

  const close = () => {
    if (remove.isPending) return; // don't bail mid-mutation
    setConfirmText("");
    setTopError(null);
    onClose();
  };

  if (!open) return null;

  const canDelete = confirmText === projectName && !remove.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-project-title"
    >
      <div className="relative w-full max-w-md bg-paper p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-crane/60 bg-crane-glow">
              <AlertTriangle className="h-5 w-5 text-crane-deep" />
            </div>
            <div>
              <h3
                id="delete-project-title"
                className="font-display text-[20px] text-ink"
              >
                Delete {projectName}?
              </h3>
              <p className="mt-1 font-sans text-[13px] text-graphite">
                This permanently removes the project and every job, target, and
                design attached to it. This cannot be undone.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={remove.isPending}
            className="rounded-full p-1 text-graphite hover:text-ink transition-colors disabled:opacity-40"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5">
          <label
            htmlFor="delete-confirm-name"
            className="font-sans text-[12px] text-graphite"
          >
            Type{" "}
            <span className="font-mono text-ink">{projectName}</span> to
            confirm.
          </label>
          <input
            id="delete-confirm-name"
            type="text"
            autoComplete="off"
            autoFocus
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="mt-2 w-full rounded-lg border border-lattice bg-paper-fold/40 px-4 py-2.5 font-mono text-[13px] text-ink outline-none placeholder:text-graphite-soft focus:border-lattice-strong"
            placeholder={projectName}
            data-testid="e2e-delete-project-confirm-input"
          />
        </div>

        {topError && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {topError}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={close}
            disabled={remove.isPending}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              setTopError(null);
              remove.mutate({ id: projectId });
            }}
            disabled={!canDelete}
            data-testid="e2e-delete-project-confirm"
            className="inline-flex items-center gap-2 rounded-full bg-crane-deep px-5 py-2.5 font-sans text-[14px] text-paper hover:bg-ink transition-colors disabled:opacity-40 disabled:hover:bg-crane-deep"
          >
            <Trash2 className="h-4 w-4" />
            {remove.isPending ? "Deleting…" : "Delete project"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default DeleteProjectDialog;
