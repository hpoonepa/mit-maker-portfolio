"use client";

import { useEffect, useState } from "react";
import { DeleteProjectDialog } from "./DeleteProjectDialog";
import { registerCommand } from "@/lib/command/registry";

export interface ProjectDeletePaletteActionProps {
  projectId: string;
  projectName: string;
}

/**
 * Headless component (renders only the dialog) that registers a per-project
 * "Delete project: <name>" entry in the Cmd+K palette while mounted.
 *
 * We mount this on the project detail page so the keyboard shortcut keeps
 * working there, even though the visible "Danger zone" lives one route
 * deeper at `/app/projects/[id]/settings`. Cleanup on unmount avoids stale
 * commands from previously-viewed projects bleeding into the palette.
 */
export function ProjectDeletePaletteAction({
  projectId,
  projectName,
}: ProjectDeletePaletteActionProps) {
  const [open, setOpen] = useState(false);

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
    <DeleteProjectDialog
      open={open}
      projectId={projectId}
      projectName={projectName}
      onClose={() => setOpen(false)}
    />
  );
}

export default ProjectDeletePaletteAction;
