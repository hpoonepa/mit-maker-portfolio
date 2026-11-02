"use client";

import { useState } from "react";
import { Copy, Check, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { validateWebhookUrl } from "@/lib/webhooks/validateUrl";
import { EventPicker, type WebhookEvent } from "./EventPicker";

export interface WebhookCreateFormProps {
  /** Parent can close the inline form when the user cancels or finishes. */
  onClose?: () => void;
  /** Parent may want to refresh the list on success: we already invalidate
   *  `webhooks.list`, but pass a hook for side-effects (toasts, etc.). */
  onCreated?: (webhookId: string) => void;
}

interface FieldErrors {
  url?: string;
  events?: string;
}

/**
 * Inline form + "reveal once" secret modal.
 *
 * Pattern mirrors the API-keys page:
 *   1. user fills form
 *   2. POST via trpc.webhooks.create → returns { webhook, secret }
 *   3. secret shown inside a blocking modal with a copy button
 *   4. modal can only be dismissed after user confirms they saved it
 */
export function WebhookCreateForm({ onClose, onCreated }: WebhookCreateFormProps) {
  const utils = trpc.useUtils();

  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [topError, setTopError] = useState<string | null>(null);

  const [revealedSecret, setRevealedSecret] = useState<
    | {
        webhookId: string;
        secret: string;
      }
    | null
  >(null);

  const create = trpc.webhooks.create.useMutation({
    // `webhooks.create` returns a `{ webhook, secret }` envelope: the
    // plaintext signing secret is surfaced here exactly once. There is no
    // rotate procedure, so this is the only time the user can capture it.
    onSuccess: ({ webhook, secret }) => {
      void utils.webhooks.list.invalidate();
      setRevealedSecret({ webhookId: webhook.id, secret });
    },
    onError: (err) => {
      setTopError(err.message ?? "Could not create webhook");
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);
    const nextErrors: FieldErrors = {};

    const urlCheck = validateWebhookUrl(url);
    if (!urlCheck.ok) nextErrors.url = urlCheck.message;

    if (events.length === 0) {
      nextErrors.events = "Pick at least one event";
    }

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    setErrors({});

    // `webhooks.create` input is `.strict()`: { url, events } only. Any extra
    // key is rejected outright, so don't add fields here without the router.
    create.mutate({
      url: urlCheck.ok ? urlCheck.url : url,
      events,
    });
  };

  const busy = create.isPending;

  return (
    <>
      <form
        onSubmit={onSubmit}
        noValidate
        className="rounded-lg border border-lattice bg-paper-fold/40 p-6 space-y-5"
        aria-describedby={topError ? "webhook-create-top-error" : undefined}
      >
        <div>
          <h2 className="font-display text-[22px] text-ink">New webhook</h2>
          <p className="mt-1 font-sans text-[13px] text-graphite">
            We&apos;ll POST signed JSON to this URL for the events you pick.
            Signatures use the secret shown once on creation.
          </p>
        </div>

        {topError && (
          <div
            id="webhook-create-top-error"
            role="alert"
            className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {topError}
          </div>
        )}

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Endpoint URL
          </span>
          <input
            type="url"
            required
            inputMode="url"
            maxLength={2048}
            placeholder="https://hooks.example.com/papercrane"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-invalid={errors.url ? true : undefined}
            aria-describedby={errors.url ? "webhook-url-err" : undefined}
            className={cn(
              "rounded-xl border bg-paper px-4 py-3 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:outline-none",
              errors.url
                ? "border-crane focus:border-crane-deep"
                : "border-lattice-strong focus:border-ink",
            )}
          />
          {errors.url && (
            <span
              id="webhook-url-err"
              className="font-sans text-[12px] text-crane-deep"
            >
              {errors.url}
            </span>
          )}
        </label>

        <div className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Events
          </span>
          <EventPicker
            value={events}
            onChange={setEvents}
            ariaInvalid={!!errors.events}
            describedBy={errors.events ? "webhook-events-err" : undefined}
          />
          {errors.events && (
            <span
              id="webhook-events-err"
              className="font-sans text-[12px] text-crane-deep"
            >
              {errors.events}
            </span>
          )}
        </div>

        <div className="flex items-center justify-end gap-2">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={busy}
            className="btn-primary disabled:opacity-60"
          >
            {busy ? "Creating…" : "Create webhook"}
          </button>
        </div>
      </form>

      {revealedSecret && (
        <SecretRevealModal
          secret={revealedSecret.secret}
          onClose={() => {
            const id = revealedSecret.webhookId;
            setRevealedSecret(null);
            onCreated?.(id);
            onClose?.();
          }}
        />
      )}
    </>
  );
}

/**
 * Blocking modal. Confirmation checkbox is required before the user can
 * dismiss: matches the spec's "I've saved this secret" pattern.
 */
export function SecretRevealModal({
  secret,
  onClose,
  title = "Save this secret now",
}: {
  secret: string;
  onClose: () => void;
  title?: string;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(secret);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }
    } catch {
      // Silent: the <code> block is still selectable.
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="secret-reveal-title"
    >
      <div className="relative w-full max-w-lg rounded-lg border border-crane-glow bg-paper p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3
              id="secret-reveal-title"
              className="font-display text-[20px] text-ink"
            >
              {title}
            </h3>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              You won&apos;t be able to see this secret again. Secret rotation
              isn&apos;t available during the beta: if you lose it, delete this
              webhook and create a new one.
            </p>
          </div>
          {/* Intentional: no close button: confirmation is required. */}
        </div>

        <div className="mt-5 flex items-stretch gap-2">
          <code className="flex-1 rounded-xl bg-paper-fold px-4 py-3 font-mono text-[13px] text-ink break-all select-all">
            {secret}
          </code>
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1.5 rounded-xl border border-lattice bg-paper px-3 font-sans text-[12px] text-ink hover:border-ink transition-colors"
            aria-label="Copy secret to clipboard"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>

        <label className="mt-5 flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-lattice-strong text-ink focus:ring-ink"
          />
          <span className="font-sans text-[13px] text-ink">
            I&apos;ve saved this secret in a safe place.
          </span>
        </label>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={!confirmed}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <X className="h-4 w-4" />
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default WebhookCreateForm;
