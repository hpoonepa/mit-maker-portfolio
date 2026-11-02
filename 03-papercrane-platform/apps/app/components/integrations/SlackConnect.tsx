"use client";

import { useState } from "react";
import { Send, X, Slack } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import {
  EventPicker,
  DEFAULT_INTEGRATION_EVENTS,
  type IntegrationEvent,
} from "./EventPicker";

interface SlackConnectProps {
  /** When provided, the form opens in "edit" mode for an existing channel. */
  existing?: {
    integrationId: string;
    channelId: string;
    webhookUrl: string;
    events: IntegrationEvent[];
    muted: boolean;
  };
  onClose?: () => void;
}

/**
 * Slack connection form.
 *
 * UX
 *   1. Inline link to the Slack admin page that creates an incoming webhook.
 *   2. Webhook URL input (must start with hooks.slack.com/services/).
 *   3. Event picker (defaults reflect the noisy/not heuristic).
 *   4. "Send test message" button: does NOT create a row, just hits the
 *      worker's test endpoint with the entered URL. Useful when copy-pasting
 *      from Slack to verify the URL works before saving.
 *   5. Save button.
 */
export function SlackConnect({ existing, onClose }: SlackConnectProps) {
  const utils = trpc.useUtils();
  const isEdit = !!existing;

  const [webhookUrl, setWebhookUrl] = useState(existing?.webhookUrl ?? "");
  const [events, setEvents] = useState<IntegrationEvent[]>(
    existing?.events ?? DEFAULT_INTEGRATION_EVENTS,
  );
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const connect = trpc.integrations.connect.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
      setSuccess("Slack connected.");
      setTimeout(() => onClose?.(), 800);
    },
    onError: (e) => setError(e.message),
  });

  const update = trpc.integrations.updateChannel.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
      setSuccess("Saved.");
    },
    onError: (e) => setError(e.message),
  });

  const test = trpc.integrations.testChannel.useMutation({
    onSuccess: (r) => {
      setError(null);
      setSuccess(r.message);
    },
    onError: (e) => setError(e.message),
  });

  const validateUrl = (): string | null => {
    if (!webhookUrl) return "Webhook URL is required.";
    if (!/^https:\/\/hooks\.slack\.com\/services\//.test(webhookUrl)) {
      return "Slack webhook URLs start with https://hooks.slack.com/services/";
    }
    return null;
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = validateUrl();
    if (v) {
      setError(v);
      return;
    }
    if (events.length === 0) {
      setError("Pick at least one event to forward.");
      return;
    }
    setError(null);
    if (isEdit) {
      update.mutate({ id: existing!.channelId, webhookUrl, events });
    } else {
      connect.mutate({ kind: "slack", webhookUrl, events, name: "" });
    }
  };

  const onTest = () => {
    if (isEdit) {
      test.mutate({ id: existing!.channelId });
    } else {
      // Pre-save test: validate shape but tell the user to save first to
      // actually deliver. We don't have an unauthenticated "test arbitrary
      // URL" endpoint: that would invite abuse. The save button is the path.
      const v = validateUrl();
      setError(v);
      if (!v) {
        setSuccess(
          "URL looks valid. Save the integration, then use the test button.",
        );
      }
    }
  };

  const busy = connect.isPending || update.isPending;

  return (
    <form onSubmit={onSubmit} className="space-y-6 rounded-lg border border-lattice bg-paper p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-lattice bg-paper-fold">
            <Slack className="h-5 w-5 text-ink" />
          </span>
          <div>
            <h2 className="font-display text-[20px] text-ink">
              {isEdit ? "Edit Slack channel" : "Connect Slack"}
            </h2>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              Forward Paper Crane events to a Slack channel via an incoming
              webhook.
            </p>
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full border border-lattice p-1.5 text-graphite hover:border-ink hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Setup instructions */}
      <div className="px-4 py-3 font-sans text-[13px] text-graphite">
        <p className="font-medium text-ink">How to create a Slack webhook</p>
        <ol className="mt-1 list-decimal pl-5 space-y-0.5">
          <li>
            Open{" "}
            <a
              href="https://api.slack.com/apps"
              target="_blank"
              rel="noreferrer"
              className="underline text-ink"
            >
              Slack apps
            </a>
            , create a new app from scratch.
          </li>
          <li>Enable “Incoming Webhooks” → Add New Webhook to Workspace.</li>
          <li>Pick the channel you want messages posted in.</li>
          <li>Copy the URL (starts with <code>hooks.slack.com/services/</code>) and paste below.</li>
        </ol>
      </div>

      <label className="block">
        <span className="block font-sans text-[12px] text-graphite-soft">
          Webhook URL
        </span>
        <input
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.slack.com/services/T000/B000/xxx"
          required
          className="mt-2 w-full rounded-lg border border-lattice bg-paper px-4 py-2.5 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
        />
      </label>

      <div>
        <span className="block font-sans text-[12px] text-graphite-soft">
          Events to forward
        </span>
        <div className="mt-2">
          <EventPicker value={events} onChange={setEvents} />
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
          {error}
        </div>
      )}
      {success && !error && (
        <div role="status" className="px-4 py-3 font-sans text-[13px] text-ink">
          {success}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={busy}
          className={cn(
            "btn-primary",
            busy && "opacity-70 cursor-not-allowed",
          )}
        >
          {isEdit ? "Save changes" : "Connect Slack"}
        </button>
        <button
          type="button"
          onClick={onTest}
          disabled={test.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-lattice bg-paper px-4 py-2 font-sans text-[13px] text-ink hover:border-ink"
        >
          <Send className="h-3.5 w-3.5" />
          Send test message
        </button>
      </div>
    </form>
  );
}

export default SlackConnect;
