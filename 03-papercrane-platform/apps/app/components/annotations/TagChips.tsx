"use client";

import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

/**
 * TagChips: colored chips on a design. Click × to detach; "Add tag" opens a
 * picker that lets you choose an existing org tag or create a new one with a
 * color picker.
 */

interface Tag {
  id: string;
  name: string;
  color: string;
}

interface Props {
  designId: string;
  tags: Tag[];
  className?: string;
}

const PALETTE = [
  "#94a3b8",
  "#f59e0b",
  "#10b981",
  "#3b82f6",
  "#a855f7",
  "#ef4444",
  "#ec4899",
  "#0ea5e9",
];

export function TagChips({ designId, tags, className }: Props) {
  const utils = trpc.useUtils();
  const palette = trpc.annotations.tags.list.useQuery();
  const create = trpc.annotations.tags.create.useMutation({
    onSuccess: () => {
      utils.annotations.tags.list.invalidate();
    },
  });
  const attach = trpc.annotations.tags.attach.useMutation({
    onSuccess: () => {
      utils.annotations.listByDesign.invalidate({ designId });
    },
  });
  const detach = trpc.annotations.tags.detach.useMutation({
    onSuccess: () => {
      utils.annotations.listByDesign.invalidate({ designId });
    },
  });

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState(PALETTE[0]!);

  const attached = useMemo(() => new Set(tags.map((t) => t.id)), [tags]);
  const candidates = useMemo(() => {
    const all = palette.data?.items ?? [];
    return all.filter((t) => !attached.has(t.id));
  }, [palette.data, attached]);

  async function handleAdd() {
    const trimmed = name.trim();
    if (!trimmed) return;
    const existing = palette.data?.items.find(
      (t) => t.name.toLowerCase() === trimmed.toLowerCase(),
    );
    if (existing) {
      attach.mutate({ designId, tagId: existing.id });
      setName("");
      setOpen(false);
      return;
    }
    try {
      const created = await create.mutateAsync({ name: trimmed, color });
      await attach.mutateAsync({ designId, tagId: created.id });
      setName("");
      setOpen(false);
    } catch {
      // surfaced by isPending/error states; nothing to do here.
    }
  }

  return (
    <div className={cn("space-y-2", className)}>
      <h3 className="font-sans text-[12px] text-graphite">
        Tags
      </h3>
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((t) => (
          <Chip
            key={t.id}
            color={t.color}
            label={t.name}
            onRemove={() => detach.mutate({ designId, tagId: t.id })}
          />
        ))}
        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-lattice-strong bg-paper px-2.5 py-0.5 font-sans text-[11px] text-graphite hover:text-ink"
          >
            <Plus className="h-3 w-3" />
            Add tag
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5 bg-paper p-1.5">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAdd();
                else if (e.key === "Escape") {
                  setOpen(false);
                  setName("");
                }
              }}
              placeholder="tag name…"
              className="w-28 rounded bg-transparent px-1.5 py-0.5 font-sans text-[12px] text-ink placeholder:text-graphite-soft focus:outline-none"
            />
            <ColorPicker value={color} onChange={setColor} />
            <button
              type="button"
              onClick={handleAdd}
              disabled={create.isPending || attach.isPending || !name.trim()}
              className="rounded bg-ink px-2 py-0.5 font-sans text-[12px] text-paper disabled:opacity-50"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setName("");
              }}
              className="rounded px-1 text-graphite-soft hover:text-ink"
              aria-label="Cancel"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {open && candidates.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            existing:
          </span>
          {candidates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                attach.mutate({ designId, tagId: t.id });
                setOpen(false);
              }}
              className="inline-flex items-center gap-1 rounded-full border border-lattice bg-paper px-2 py-0.5 font-sans text-[11px] text-graphite hover:text-ink"
            >
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{ background: t.color }}
              />
              {t.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({
  color,
  label,
  onRemove,
}: {
  color: string;
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-sans text-[11px]"
      style={{
        background: `${color}1A`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove tag ${label}`}
          className="ml-0.5 rounded-full p-0.5 hover:bg-black/5"
          style={{ color }}
        >
          <X className="h-2.5 w-2.5" />
        </button>
      )}
    </span>
  );
}

function ColorPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (c: string) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Tag color" className="flex items-center gap-1">
      {PALETTE.map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          onClick={() => onChange(c)}
          className={cn(
            "h-4 w-4 rounded-full ring-2 ring-offset-1",
            value === c ? "ring-ink" : "ring-transparent",
          )}
          style={{ background: c }}
          aria-label={`Color ${c}`}
        />
      ))}
    </div>
  );
}
