"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { renderMarkdown } from "./markdown";

/**
 * CommentEditor: markdown textarea with @mention typeahead and a preview tab.
 *
 * Mentions
 *   When the caret immediately follows `@<token>` (where `<token>` may be
 *   empty), we open a popover seeded from the `members` prop and filtered by
 *   the running token. Selecting an entry replaces `@<token>` with
 *   `@<member.name>` (no space ⇒ `@harsha`). The body is plain markdown; the
 *   renderer recognises `@name` against the same roster on display.
 *
 * Tabs
 *   "Write" shows the textarea; "Preview" runs `renderMarkdown(body, members)`
 *   and dumps escaped HTML into a div.
 */

export interface OrgMember {
  userId: string;
  name: string | null;
  email: string;
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  members: OrgMember[];
  busy?: boolean;
  placeholder?: string;
  submitLabel?: string;
  autoFocus?: boolean;
}

export function CommentEditor({
  value,
  onChange,
  onSubmit,
  onCancel,
  members,
  busy = false,
  placeholder = "Write a comment… use @ to mention",
  submitLabel = "Comment",
  autoFocus = false,
}: Props) {
  const [tab, setTab] = useState<"write" | "preview">("write");
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const [mention, setMention] = useState<{
    token: string;
    start: number;
    end: number;
  } | null>(null);

  useEffect(() => {
    if (autoFocus && taRef.current) taRef.current.focus();
  }, [autoFocus]);

  const filtered = useMemo(() => {
    if (!mention) return [];
    const q = mention.token.toLowerCase();
    return members
      .filter((m) => {
        const n = (m.name ?? m.email).toLowerCase();
        return n.includes(q);
      })
      .slice(0, 6);
  }, [mention, members]);

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const text = e.target.value;
    onChange(text);
    detectMention(text, e.target.selectionStart);
  }

  function detectMention(text: string, caret: number) {
    // Walk back from caret looking for `@` not preceded by an identifier char.
    let i = caret - 1;
    while (i >= 0) {
      const ch = text[i];
      if (ch === "@") {
        const prev = i > 0 ? text[i - 1] : " ";
        if (prev && /[A-Za-z0-9_.@-]/.test(prev)) {
          setMention(null);
          return;
        }
        const token = text.slice(i + 1, caret);
        if (/^[A-Za-z0-9._-]*$/.test(token)) {
          setMention({ token, start: i, end: caret });
          return;
        }
        setMention(null);
        return;
      }
      if (!/[A-Za-z0-9._-]/.test(ch ?? "")) break;
      i--;
    }
    setMention(null);
  }

  function pickMention(member: OrgMember) {
    if (!mention) return;
    const handle = (member.name ?? member.email).replace(/\s+/g, "");
    const before = value.slice(0, mention.start);
    const after = value.slice(mention.end);
    const next = `${before}@${handle} ${after}`;
    onChange(next);
    setMention(null);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        const caret = before.length + handle.length + 2;
        ta.focus();
        ta.setSelectionRange(caret, caret);
      }
    });
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mention && filtered.length > 0) {
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pickMention(filtered[0]!);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(null);
        return;
      }
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (value.trim()) onSubmit();
    }
  }

  return (
    <div className="bg-paper">
      <div className="flex items-center justify-between px-3 py-1.5">
        <div className="flex gap-1">
          <TabButton active={tab === "write"} onClick={() => setTab("write")}>
            Write
          </TabButton>
          <TabButton active={tab === "preview"} onClick={() => setTab("preview")}>
            Preview
          </TabButton>
        </div>
        <span className="font-sans text-[12px] text-graphite-soft">
          markdown · ⌘⏎ to send
        </span>
      </div>

      {tab === "write" ? (
        <div className="relative">
          <textarea
            ref={taRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKey}
            placeholder={placeholder}
            rows={4}
            className="w-full resize-y rounded-b-2xl bg-transparent px-4 py-3 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:outline-none"
          />
          {mention && filtered.length > 0 && (
            <ul
              role="listbox"
              aria-label="Mention members"
              className="absolute left-3 top-full z-20 mt-1 w-64 overflow-hidden rounded-xl border border-lattice-strong bg-paper shadow-lg"
            >
              {filtered.map((m, idx) => (
                <li key={m.userId}>
                  <button
                    type="button"
                    onClick={() => pickMention(m)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left font-sans text-[13px] hover:bg-paper-fold",
                      idx === 0 && "bg-paper-fold/60",
                    )}
                  >
                    <span
                      aria-hidden
                      className="grid h-6 w-6 place-items-center rounded-full bg-ink font-mono text-[10px] text-paper"
                    >
                      {(m.name ?? m.email)[0]?.toUpperCase()}
                    </span>
                    <span className="text-ink">{m.name ?? m.email}</span>
                    {m.name && (
                      <span className="ml-auto truncate text-[11px] text-graphite-soft">
                        {m.email}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div
          className="min-h-[6rem] px-4 py-3 font-sans text-[14px] text-ink"

          dangerouslySetInnerHTML={{ __html: renderMarkdown(value, members) }}
        />
      )}

      <div className="flex items-center justify-end gap-2 px-3 py-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink disabled:opacity-50"
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy || !value.trim()}
          className="rounded-lg border border-ink bg-ink px-3 py-1.5 font-sans text-[12px] text-paper hover:bg-graphite disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Sending…" : submitLabel}
        </button>
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 font-sans text-[12px]",
        active
          ? "bg-paper-fold text-ink"
          : "text-graphite-soft hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
