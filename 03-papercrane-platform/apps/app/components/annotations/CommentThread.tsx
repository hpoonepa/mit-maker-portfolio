"use client";

import { useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { CommentEditor, type OrgMember } from "./CommentEditor";
import { renderMarkdown } from "./markdown";

/**
 * CommentThread: full markdown thread for a design.
 *
 * Renders existing annotations top-down (oldest first), an inline edit form
 * on the author's own rows, and a sticky composer at the bottom seeded with
 * the org member roster for @mention typeahead.
 */

interface Annotation {
  id: string;
  designId: string;
  authorId: string;
  authorName: string | null;
  authorEmail: string | null;
  body: string;
  createdAt: string;
  updatedAt: string;
  canEdit: boolean;
}

interface Props {
  designId: string;
  annotations: Annotation[];
  members: OrgMember[];
  onMutated?: () => void;
}

export function CommentThread({
  designId,
  annotations,
  members,
  onMutated,
}: Props) {
  const utils = trpc.useUtils();
  const create = trpc.annotations.create.useMutation({
    onSuccess: () => {
      utils.annotations.listByDesign.invalidate({ designId });
      onMutated?.();
    },
  });
  const [draft, setDraft] = useState("");

  return (
    <section className="p-5">
      <header className="flex items-baseline justify-between">
        <h3 className="font-sans text-[12px] text-graphite">
          Comments
        </h3>
        <span className="font-sans text-[11px] text-graphite-soft">
          {annotations.length} {annotations.length === 1 ? "note" : "notes"}
        </span>
      </header>

      {annotations.length > 0 ? (
        <ul className="mt-4 space-y-4">
          {annotations.map((a) => (
            <li key={a.id}>
              <CommentRow
                annotation={a}
                designId={designId}
                members={members}
                onMutated={onMutated}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 font-sans text-[13px] text-graphite-soft">
          No comments yet: start the thread.
        </p>
      )}

      <div className="mt-5">
        <CommentEditor
          value={draft}
          onChange={setDraft}
          onSubmit={() => {
            if (!draft.trim()) return;
            create.mutate(
              { designId, body: draft },
              {
                onSuccess: () => setDraft(""),
              },
            );
          }}
          members={members}
          busy={create.isPending}
          submitLabel="Comment"
        />
      </div>
    </section>
  );
}

function CommentRow({
  annotation,
  designId,
  members,
  onMutated,
}: {
  annotation: Annotation;
  designId: string;
  members: OrgMember[];
  onMutated?: () => void;
}) {
  const utils = trpc.useUtils();
  const update = trpc.annotations.update.useMutation({
    onSuccess: () => {
      utils.annotations.listByDesign.invalidate({ designId });
      onMutated?.();
    },
  });
  const remove = trpc.annotations.delete.useMutation({
    onSuccess: () => {
      utils.annotations.listByDesign.invalidate({ designId });
      onMutated?.();
    },
  });

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(annotation.body);

  const initial = (annotation.authorName ?? annotation.authorEmail ?? "?")[0]?.toUpperCase();
  const displayName = annotation.authorName ?? annotation.authorEmail ?? "Unknown";
  const edited =
    annotation.updatedAt &&
    new Date(annotation.updatedAt).getTime() -
      new Date(annotation.createdAt).getTime() >
      1000;

  return (
    <article className="flex gap-3">
      <div
        aria-hidden
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink font-mono text-[11px] text-paper"
      >
        {initial}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="font-sans text-[13px] text-ink">
            <span className="font-medium">{displayName}</span>
            <span className="ml-2 text-[11px] text-graphite-soft">
              {formatRelative(annotation.createdAt)}
              {edited && " · edited"}
            </span>
          </p>
          {annotation.canEdit && !editing && (
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => {
                  setDraft(annotation.body);
                  setEditing(true);
                }}
                aria-label="Edit comment"
                className="rounded p-1 text-graphite-soft hover:text-ink"
              >
                <Pencil className="h-3 w-3" />
              </button>
              <button
                type="button"
                onClick={() => {
                  if (confirm("Delete this comment?")) {
                    remove.mutate({ id: annotation.id });
                  }
                }}
                aria-label="Delete comment"
                className="rounded p-1 text-graphite-soft hover:text-crane-deep"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {editing ? (
          <div className="mt-2">
            <CommentEditor
              value={draft}
              onChange={setDraft}
              onSubmit={() => {
                if (!draft.trim()) return;
                update.mutate(
                  { id: annotation.id, body: draft },
                  {
                    onSuccess: () => setEditing(false),
                  },
                );
              }}
              onCancel={() => setEditing(false)}
              members={members}
              busy={update.isPending}
              submitLabel="Save"
              autoFocus
            />
          </div>
        ) : (
          <div
            className={cn(
              "mt-1 font-sans text-[14px] leading-relaxed text-ink",
              "[&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
              "[&_code]:rounded [&_code]:bg-paper-fold [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px]",
              "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:border-lattice [&_pre]:bg-paper [&_pre]:p-3 [&_pre]:font-mono [&_pre]:text-[12px]",
              "[&_a]:text-ink [&_a]:underline [&_a:hover]:text-crane-deep",
              "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
              "[&_.mention]:rounded [&_.mention]:bg-crane-glow [&_.mention]:px-1 [&_.mention]:font-medium [&_.mention]:text-crane-deep",
            )}

            dangerouslySetInnerHTML={{
              __html: renderMarkdown(annotation.body, members),
            }}
          />
        )}
      </div>
    </article>
  );
}

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${Math.max(0, sec)}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}
