"use client";

import Link from "next/link";
import {
  Slack,
  MessageSquare,
  Plus,
  PauseCircle,
  PlayCircle,
  Trash2,
  Send,
} from "lucide-react";
import { useMemo, useState } from "react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { SlackConnect } from "@/components/integrations/SlackConnect";
import { DiscordConnect } from "@/components/integrations/DiscordConnect";
import { ModalConnect } from "@/components/integrations/ModalConnect";
import type { IntegrationEvent } from "@/components/integrations/EventPicker";

/**
 * `/app/settings/integrations`: manage Modal compute plus Slack/Discord chat connections.
 *
 * Layout
 *   1. Header
 *   2. Pending-form area: shows a SlackConnect or DiscordConnect form when
 *      the user clicks "Connect Slack" or "Connect Discord".
 *   3. List of existing channels grouped by integration kind, with mute
 *      toggle, test-fire, edit (re-uses the connect form), and disconnect.
 *
 * The page is intentionally lighter than `/app/settings/webhooks`: chat
 * integrations don't need delivery logs (Slack/Discord show their own
 * history) or signature documentation. Mute + test cover 95% of the
 * day-to-day "is this still working?" question.
 */

interface ChannelRow {
  id: string;
  integrationId: string;
  webhookUrl: string;
  events: string[];
  muted: boolean;
}

interface IntegrationRow {
  id: string;
  kind: "slack" | "discord";
  name: string;
  channels: ChannelRow[];
}

function coerceItems(data: unknown): IntegrationRow[] {
  if (!data) return [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyData = data as any;
  const items: unknown = anyData?.items ?? anyData;
  if (!Array.isArray(items)) return [];
  return items as IntegrationRow[];
}

export default function IntegrationsSettingsPage() {
  const utils = trpc.useUtils();
  const query = trpc.integrations.list.useQuery();
  const items = useMemo(() => coerceItems(query.data), [query.data]);

  const [pending, setPending] = useState<"slack" | "discord" | null>(null);
  const [editChannelId, setEditChannelId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; message: string } | null>(null);

  const update = trpc.integrations.updateChannel.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
    },
    onError: (e) => setToast({ kind: "err", message: e.message }),
  });

  const test = trpc.integrations.testChannel.useMutation({
    onSuccess: (r) => setToast({ kind: "ok", message: r.message }),
    onError: (e) => setToast({ kind: "err", message: e.message }),
  });

  const disconnect = trpc.integrations.disconnect.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
      setToast({ kind: "ok", message: "Integration disconnected." });
    },
    onError: (e) => setToast({ kind: "err", message: e.message }),
  });

  // Find the integration row that owns a given channel: used to seed the
  // edit form with the right kind.
  const editTarget = useMemo(() => {
    if (!editChannelId) return null;
    for (const i of items) {
      const ch = i.channels.find((c) => c.id === editChannelId);
      if (ch) {
        return { kind: i.kind, integration: i, channel: ch };
      }
    }
    return null;
  }, [items, editChannelId]);

  return (
    <div className="space-y-10">
      <header>
        <p className="font-sans text-[12px] text-graphite-soft">
          Integrations
        </p>
        <h1 className="font-display text-display-md text-ink">
          Compute &amp; notifications
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          Connect Modal for real GPU jobs, then forward job, billing, and usage
          events to chat channels.
        </p>
        <p className="mt-3 font-sans text-[13px] text-graphite">
          Looking for HMAC-signed webhooks for your own systems? See{" "}
          <Link href="/app/settings/webhooks" className="underline text-ink">
            Webhooks
          </Link>
          .
        </p>
      </header>

      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {toast?.message}
      </div>
      {toast && (
        <div
          className={cn(
            "rounded-lg border px-4 py-3 font-sans text-[13px]",
            toast.kind === "ok"
              ? "border-lattice bg-paper-fold text-ink"
              : "border-crane/40 bg-crane-glow text-crane-deep",
          )}
        >
          {toast.message}
        </div>
      )}

      <ModalConnect />

      {/* Connect actions */}
      {!pending && !editChannelId && (
        <div className="grid gap-4 md:grid-cols-2">
          <ConnectCard
            kind="slack"
            onConnect={() => setPending("slack")}
            existing={items.find((i) => i.kind === "slack")}
          />
          <ConnectCard
            kind="discord"
            onConnect={() => setPending("discord")}
            existing={items.find((i) => i.kind === "discord")}
          />
        </div>
      )}

      {pending === "slack" && (
        <SlackConnect onClose={() => setPending(null)} />
      )}
      {pending === "discord" && (
        <DiscordConnect onClose={() => setPending(null)} />
      )}

      {editTarget && editTarget.kind === "slack" && (
        <SlackConnect
          existing={{
            integrationId: editTarget.integration.id,
            channelId: editTarget.channel.id,
            webhookUrl: editTarget.channel.webhookUrl,
            events: editTarget.channel.events as IntegrationEvent[],
            muted: editTarget.channel.muted,
          }}
          onClose={() => setEditChannelId(null)}
        />
      )}
      {editTarget && editTarget.kind === "discord" && (
        <DiscordConnect
          existing={{
            integrationId: editTarget.integration.id,
            channelId: editTarget.channel.id,
            webhookUrl: editTarget.channel.webhookUrl,
            events: editTarget.channel.events as IntegrationEvent[],
            muted: editTarget.channel.muted,
          }}
          onClose={() => setEditChannelId(null)}
        />
      )}

      {/* Existing list */}
      <section className="space-y-4">
        <h2 className="font-display text-[18px] text-ink">Connected channels</h2>
        {query.isLoading ? (
          <div className="px-8 py-10 text-center font-sans text-[14px] text-graphite">
            Loading…
          </div>
        ) : items.length === 0 ? (
          <div className="px-8 py-10 text-center font-sans text-[14px] text-graphite">
            No chat integrations yet. Connect Slack or Discord above.
          </div>
        ) : (
          <ul role="list" className="space-y-3">
            {items.flatMap((integ) =>
              integ.channels.map((ch) => (
                <li
                  key={ch.id}
                  className="flex flex-wrap items-center gap-4 bg-paper px-4 py-3"
                >
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-lattice bg-paper-fold">
                    {integ.kind === "slack" ? (
                      <Slack className="h-4 w-4 text-ink" />
                    ) : (
                      <MessageSquare className="h-4 w-4 text-ink" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[13px] text-ink">
                      {redactWebhookUrl(ch.webhookUrl)}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      {ch.events.length === 0 ? (
                        <span className="font-sans text-[12px] text-graphite-soft">
                          no events
                        </span>
                      ) : (
                        ch.events.map((ev) => (
                          <span
                            key={ev}
                            className="rounded-full border border-lattice bg-paper-fold px-2 py-0.5 font-sans text-[12px] text-graphite"
                          >
                            {ev}
                          </span>
                        ))
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => test.mutate({ id: ch.id })}
                      disabled={test.isPending}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink"
                      aria-label="Send test message"
                    >
                      <Send className="h-3.5 w-3.5" />
                      Test
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        update.mutate({ id: ch.id, muted: !ch.muted })
                      }
                      className="inline-flex items-center gap-1.5 rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink"
                      aria-pressed={ch.muted}
                    >
                      {ch.muted ? (
                        <>
                          <PlayCircle className="h-3.5 w-3.5" /> Resume
                        </>
                      ) : (
                        <>
                          <PauseCircle className="h-3.5 w-3.5" /> Mute
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditChannelId(ch.id)}
                      className="rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm("Disconnect this integration?")) {
                          disconnect.mutate({ id: integ.id });
                        }
                      }}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-crane-deep hover:border-crane"
                      aria-label="Disconnect"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              )),
            )}
          </ul>
        )}
      </section>
    </div>
  );
}

interface ConnectCardProps {
  kind: "slack" | "discord";
  onConnect: () => void;
  existing?: IntegrationRow;
}

function ConnectCard({ kind, onConnect, existing }: ConnectCardProps) {
  const Icon = kind === "slack" ? Slack : MessageSquare;
  const label = kind === "slack" ? "Slack" : "Discord";
  const description =
    kind === "slack"
      ? "Block-formatted messages with a View button."
      : "Coloured embeds with project, tool, and metric fields.";

  return (
    <div className="bg-paper p-6">
      <div className="flex items-start gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-lattice bg-paper-fold">
          <Icon className="h-5 w-5 text-ink" />
        </span>
        <div className="flex-1">
          <h3 className="font-display text-[18px] text-ink">{label}</h3>
          <p className="mt-1 font-sans text-[13px] text-graphite">
            {description}
          </p>
          {existing && existing.channels.length > 0 ? (
            <p className="mt-2 font-sans text-[12px] text-graphite-soft">
              {existing.channels.length} channel
              {existing.channels.length === 1 ? "" : "s"} connected.
            </p>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={onConnect}
        className="btn-primary mt-5"
      >
        <Plus className="h-4 w-4" />
        {existing ? `Add another ${label} channel` : `Connect ${label}`}
      </button>
    </div>
  );
}

/**
 * Hide the secret part of an incoming-webhook URL when rendering in the
 * list. Slack URLs end in `.../services/T<team>/B<id>/<token>`; we keep the
 * first two path segments after `services/` (so the user can still tell
 * channels apart) and replace the token with bullets.
 */
function redactWebhookUrl(url: string): string {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts.length <= 2) return `${u.host}${u.pathname}`;
    const last = parts[parts.length - 1] ?? "";
    const masked = last.length > 0 ? "•".repeat(Math.min(last.length, 8)) : "•••";
    parts[parts.length - 1] = masked;
    return `${u.host}/${parts.join("/")}`;
  } catch {
    return url.slice(0, 40) + (url.length > 40 ? "…" : "");
  }
}
