"use client";

import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, Trash2 } from "lucide-react";
import { DeleteProjectDialog } from "./DeleteProjectDialog";

export interface ProjectCardMenuProps {
  projectId: string;
  projectName: string;
}

/**
 * Kebab menu (•••) overlaid on each project card in the list view.
 *
 * The menu is intentionally a sibling of the card link: not a child -
 * because Next/Link captures click events on the entire subtree. We sit
 * in the card's top-right corner with `pointer-events-auto` while the
 * card link itself stays clickable; clicking the kebab opens a small
 * floating menu with the destructive option.
 */
export function ProjectCardMenu({
  projectId,
  projectName,
}: ProjectCardMenuProps) {
  const [open, setOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Click-outside / Escape to dismiss the dropdown.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <div
        ref={menuRef}
        className="absolute right-3 top-3 z-10"
        // Stop the Link parent from intercepting menu interactions.
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <button
          type="button"
          aria-label="Project actions"
          aria-haspopup="menu"
          aria-expanded={open}
          data-testid={`e2e-project-card-menu-${projectId}`}
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-graphite hover:bg-paper hover:text-ink transition-colors"
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
        {open && (
          <div
            role="menu"
            className="absolute right-0 mt-1 w-44 overflow-hidden rounded-lg border border-lattice bg-paper py-1"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                setDeleteOpen(true);
              }}
              data-testid={`e2e-project-card-delete-${projectId}`}
              className="flex w-full items-center gap-2 px-4 py-2 text-left font-sans text-[13px] text-crane-deep hover:bg-crane-glow/60 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete project
            </button>
          </div>
        )}
      </div>

      <DeleteProjectDialog
        open={deleteOpen}
        projectId={projectId}
        projectName={projectName}
        // Stay on the list: the row will disappear after invalidation.
        redirectTo="/app/projects"
        onClose={() => setDeleteOpen(false)}
      />
    </>
  );
}

export default ProjectCardMenu;
