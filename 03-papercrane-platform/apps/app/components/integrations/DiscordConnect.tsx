"use client";

import { useState } from "react";
import { Send, X, MessageSquare } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import {
  EventPicker,
  DEFAULT_INTEGRATION_EVENTS,
  type IntegrationEvent,
} from "./EventPicker";

interface DiscordConnectProps {
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
 * Discord connection form. Mirrors `SlackConnect`: see that file for the
 * design rationale; the only differences are:
 *   1. URL prefix validation (discord.com/api/webhooks/...)
 *   2. Setup instructions point at Discord's "Edit Channel → Integrations
 *      → Webhooks" flow.
 *   3. Icon + brand label.
 */
export function DiscordConnect({ existing, onClose }: DiscordConnectProps) {
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
      setSuccess("Discord connected.");
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
    if (!/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\//.test(webhookUrl)) {
      return "Discord webhook URLs start with https://discord.com/api/webhooks/";
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
      connect.mutate({ kind: "discord", webhookUrl, events, name: "" });
    }
  };

  const onTest = () => {
    if (isEdit) {
      test.mutate({ id: existing!.channelId });
    } else {
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
            <MessageSquare className="h-5 w-5 text-ink" />
          </span>
          <div>
            <h2 className="font-display text-[20px] text-ink">
              {isEdit ? "Edit Discord channel" : "Connect Discord"}
            </h2>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              Forward Paper Crane events to a Discord channel via a webhook.
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

      <div className="px-4 py-3 font-sans text-[13px] text-graphite">
        <p className="font-medium text-ink">How to create a Discord webhook</p>
        <ol className="mt-1 list-decimal pl-5 space-y-0.5">
          <li>Open Discord → right-click your channel → Edit Channel.</li>
          <li>Integrations → Webhooks → New Webhook.</li>
          <li>Name it &ldquo;Paper Crane&rdquo; and choose the target channel.</li>
          <li>Copy the URL (starts with <code>discord.com/api/webhooks/</code>) and paste below.</li>
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
          placeholder="https://discord.com/api/webhooks/000/aaa-bbb"
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
          {isEdit ? "Save changes" : "Connect Discord"}
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

export default DiscordConnect;
