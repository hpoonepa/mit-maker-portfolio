"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { DeleteProjectDialog } from "./DeleteProjectDialog";
import { registerCommand } from "@/lib/command/registry";

export interface ProjectDangerZoneProps {
  projectId: string;
  projectName: string;
}

/**
 * Client-only "Danger zone" section rendered at the bottom of the project
 * detail page. Owns the `DeleteProjectDialog` open state so the surrounding
 * page can stay a server component.
 *
 * Side-effect: while this component is mounted (i.e. the user is on a
 * project detail page), it registers a "Delete project" entry in the
 * Cmd+K command palette. Selecting it pops the same destructive-confirm
 * dialog the danger-zone button does.
 */
export function ProjectDangerZone({
  projectId,
  projectName,
}: ProjectDangerZoneProps) {
  const [open, setOpen] = useState(false);

  // Register a project-scoped Cmd+K action while this page is mounted.
  // The palette's custom-command registry is scoped per process, so the
  // unregister cleanup matters: leaving stale commands around from a
  // previously-viewed project would let users delete the wrong thing.
  useEffect(() => {
    const unregister = registerCommand({
      id: `action.delete-project.${projectId}`,
      title: `Delete project: ${projectName}`,
      subtitle: "Permanently remove this project and all its jobs",
      group: "Actions",
      kind: "action",
      keywords: ["delete", "remove", "trash", "destroy", "project"],
      action: () => setOpen(true),
    });
    return unregister;
  }, [projectId, projectName]);

  return (
    <section
      data-testid="e2e-project-danger-zone"
      className="rounded-lg border border-crane/30 bg-crane-glow/30 px-6 py-5"
    >
      <div className="flex items-start justify-between gap-6">
        <div>
          <h2 className="font-display text-[18px] text-crane-deep">
            Danger zone
          </h2>
          <p className="mt-1 max-w-xl font-sans text-[13px] text-graphite">
            Deleting this project removes every target, job, and design
            attached to it. There is no undo.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-testid="e2e-project-delete-button"
          className="inline-flex shrink-0 items-center gap-2 rounded-full border border-crane/60 bg-paper px-4 py-2 font-sans text-[13px] text-crane-deep hover:bg-crane-glow transition-colors"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete project
        </button>
      </div>

      <DeleteProjectDialog
        open={open}
        projectId={projectId}
        projectName={projectName}
        onClose={() => setOpen(false)}
      />
    </section>
  );
}

export default ProjectDangerZone;
