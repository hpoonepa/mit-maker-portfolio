"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GitBranch, X, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";

/**
 * Fork-project button + inline name dialog.
 *
 * Forks copy the source project's targets and hotspots into a brand-new
 * project, link back via `metadata.forkedFrom` on the seed v1 snapshot,
 * and leave the source untouched. We expose this as a button-with-popover
 * (rather than a separate page) because the only required input is the
 * new project's name: anything heavier belongs in the project settings
 * page on the fork itself.
 */
export interface ForkButtonProps {
  projectId: string;
  projectName: string;
  /** Optional: fork from a specific historical version instead of live state. */
  fromVersion?: number;
  /** Visual variant. `inline` = embed in a diff/version pane. */
  variant?: "primary" | "inline";
  /** Override the rendered DOM id (used to scroll-to from the history page). */
  domId?: string;
}

export function ForkButton({
  projectId,
  projectName,
  fromVersion,
  variant = "primary",
  domId,
}: ForkButtonProps) {
  const router = useRouter();
  const utils = trpc.useUtils();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(`${projectName} (fork)`);
  const [error, setError] = useState<string | null>(null);

  const fork = trpc.projects.fork.useMutation({
    onSuccess: (created) => {
      toast({
        title: "Project forked",
        description: `"${created.name}" is ready in your workspace.`,
        variant: "success",
      });
      void utils.projects.list.invalidate();
      setOpen(false);
      setName(`${projectName} (fork)`);
      setError(null);
      router.push(`/app/projects/${created.id}`);
    },
    onError: (err) => {
      setError(err.message ?? "Could not fork project.");
    },
  });

  const submit = () => {
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name cannot be empty.");
      return;
    }
    fork.mutate({
      projectId,
      fromVersion,
      name: trimmed,
    });
  };

  const triggerClasses =
    variant === "primary"
      ? "inline-flex items-center gap-2 rounded-full bg-crane-deep px-5 py-2.5 min-h-[44px] sm:min-h-0 font-sans text-[14px] text-paper hover:bg-ink transition-colors"
      : "inline-flex items-center gap-2 rounded-full border border-lattice bg-paper-fold/40 px-4 py-2 min-h-[44px] sm:min-h-0 font-sans text-[13px] text-graphite hover:text-ink transition-colors";

  return (
    <div id={domId ?? `fork-${fromVersion ?? "live"}`} className="relative">
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className={triggerClasses}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="e2e-fork-button"
      >
        <GitBranch className="h-3.5 w-3.5" />
        Fork project
        {fromVersion ? (
          <span className="font-mono text-[11px] text-paper/70">
            (v{fromVersion})
          </span>
        ) : null}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="false"
          aria-label="Fork project"
          className="absolute right-0 top-[calc(100%+8px)] z-30 w-full min-w-[300px] max-w-md rounded-lg border border-lattice bg-paper p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h4 className="font-display text-[18px] text-ink">
                Fork {projectName}
              </h4>
              <p className="mt-1 font-sans text-[12px] text-graphite">
                Creates a new project with the same target and hotspots. The
                original is untouched.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              disabled={fork.isPending}
              className="rounded-full p-1 text-graphite hover:text-ink transition-colors disabled:opacity-40"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <label
            htmlFor="fork-name-input"
            className="mt-4 block font-sans text-[12px] text-graphite"
          >
            New project name
          </label>
          <input
            id="fork-name-input"
            type="text"
            autoFocus
            value={name}
            disabled={fork.isPending}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            className="mt-2 w-full rounded-lg border border-lattice bg-paper-fold/40 px-4 py-2.5 font-sans text-[14px] text-ink outline-none placeholder:text-graphite-soft focus:border-lattice-strong"
            data-testid="e2e-fork-name-input"
          />

          {error && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-crane/40 bg-crane-glow px-3 py-2 font-sans text-[12px] text-crane-deep"
            >
              {error}
            </div>
          )}

          <div className="mt-5 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              disabled={fork.isPending}
              className="rounded-full px-4 py-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={fork.isPending || !name.trim()}
              className="inline-flex items-center gap-2 rounded-full bg-crane-deep px-4 py-2 font-sans text-[13px] text-paper hover:bg-ink transition-colors disabled:opacity-40"
              data-testid="e2e-fork-confirm"
            >
              {fork.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <GitBranch className="h-3.5 w-3.5" />
              )}
              {fork.isPending ? "Forking…" : "Create fork"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ForkButton;
