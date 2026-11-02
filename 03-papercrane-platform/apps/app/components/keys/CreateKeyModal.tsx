"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { ApiKeyScopeSchema, type ApiKeyScope } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { mapTrpcError } from "@/lib/errors/trpc-error-map";
import { formatScope, formatScopeDescription, SCOPE_ORDER } from "@/lib/keys/formatScope";
import { SecretRevealModal } from "./SecretRevealModal";

export interface CreateKeyModalProps {
  open: boolean;
  onClose: () => void;
}

const EXPIRY_OPTIONS = [
  { value: "never", label: "Never expires", days: null },
  { value: "30d", label: "30 days", days: 30 },
  { value: "90d", label: "90 days", days: 90 },
  { value: "1y", label: "1 year", days: 365 },
] as const;

type ExpiryValue = (typeof EXPIRY_OPTIONS)[number]["value"];

/**
 * Modal for minting a new API key.
 *
 * Stages:
 *   1. form: name + scopes + optional expiration
 *   2. on success: dismount form, mount <SecretRevealModal> with plaintext
 *   3. SecretRevealModal onClose → invalidate list + dismiss everything
 *
 * Validation:
 *   - name: 1..120 chars (mirrors server input)
 *   - scopes: ≥ 1 (otherwise the key is useless and the server would reject)
 *   - expiration: null or future date
 *
 * The form clears locally on close so a re-open starts fresh.
 */
export function CreateKeyModal({ open, onClose }: CreateKeyModalProps) {
  const utils = trpc.useUtils();

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>([]);
  const [expiry, setExpiry] = useState<ExpiryValue>("never");
  const [topError, setTopError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<string | null>(null);

  const create = trpc.keys.create.useMutation({
    onSuccess: (result) => {
      void utils.keys.list.invalidate();
      setRevealed(result.secret);
    },
    onError: (err) => {
      // CONFLICT here means "a key with that name already exists": the
      // mapper turns that into actionable copy instead of a stack trace.
      const mapped = mapTrpcError(err, {
        resource: "API key",
        conflictField: "name",
      });
      setTopError(mapped.message);
    },
  });

  const reset = () => {
    setName("");
    setScopes([]);
    setExpiry("never");
    setTopError(null);
    setRevealed(null);
  };

  const closeEverything = () => {
    reset();
    onClose();
  };

  if (!open) return null;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);

    const trimmed = name.trim();
    if (trimmed.length < 1 || trimmed.length > 120) {
      setTopError("Name must be 1–120 characters");
      return;
    }
    if (scopes.length === 0) {
      setTopError("Pick at least one scope");
      return;
    }

    const opt = EXPIRY_OPTIONS.find((o) => o.value === expiry);
    const expiresAt =
      opt && opt.days !== null
        ? new Date(Date.now() + opt.days * 24 * 60 * 60 * 1000)
        : null;

    create.mutate({ name: trimmed, scopes, expiresAt });
  };

  const busy = create.isPending;

  if (revealed) {
    return (
      <SecretRevealModal
        secret={revealed}
        title="Your new API key"
        description="Copy it now: this is the only time we'll show it."
        onClose={closeEverything}
      />
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-key-title"
    >
      <form
        onSubmit={onSubmit}
        noValidate
        className="relative w-full max-w-lg rounded-lg border border-lattice bg-paper p-6 space-y-5"
        aria-describedby={topError ? "create-key-top-error" : undefined}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 id="create-key-title" className="font-display text-[20px] text-ink">
              New API key
            </h3>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              Keys authenticate requests from scripts, CI, and tools. The
              plaintext is shown once and never stored.
            </p>
          </div>
          <button
            type="button"
            onClick={closeEverything}
            className="rounded-full p-1 text-graphite hover:text-ink transition-colors"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {topError && (
          <div
            id="create-key-top-error"
            role="alert"
            className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {topError}
          </div>
        )}

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Name
          </span>
          <input
            type="text"
            required
            maxLength={120}
            placeholder="ci-runner or lambert-laptop"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between">
            <span className="font-sans text-[12px] text-graphite-soft">
              Scopes
            </span>
            <span
              className="font-mono text-[11px] text-graphite-soft"
              aria-live="polite"
            >
              {scopes.length === 0
                ? "pick at least one"
                : `${scopes.length} selected`}
            </span>
          </div>
          <div className="divide-y divide-lattice">
            {SCOPE_ORDER.map((s) => {
              const checked = scopes.includes(s);
              const parsed = ApiKeyScopeSchema.safeParse(s);
              if (!parsed.success) return null;
              return (
                <label
                  key={s}
                  className={cn(
                    "flex items-start gap-3 px-4 py-2.5 cursor-pointer hover:bg-paper/60",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      setScopes((prev) =>
                        prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
                      )
                    }
                    className="mt-1 h-4 w-4 rounded border-lattice-strong text-ink focus:ring-ink"
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block font-mono text-[13px] text-ink">
                      {formatScope(s)}
                    </span>
                    <span className="block font-sans text-[12px] text-graphite">
                      {formatScopeDescription(s)}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Expiration
          </span>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value as ExpiryValue)}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[14px] text-ink focus:border-ink focus:outline-none"
          >
            {EXPIRY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={closeEverything}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-primary disabled:opacity-60"
          >
            {busy ? "Creating…" : "Create key"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default CreateKeyModal;
