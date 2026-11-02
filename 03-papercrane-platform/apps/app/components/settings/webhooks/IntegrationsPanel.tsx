"use client";

import { useMemo, useState } from "react";
import {
  Slack,
  MessageSquare,
  Plus,
  PauseCircle,
  PlayCircle,
  Trash2,
  X,
} from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

/**
 * Wave-D: Slack/Discord webhook integration UI for the settings page.
 *
 * Wires `integrations.*` tRPC procs (list/connect/updateChannel/disconnect)
 * to a compact list with:
 *   - kind chip (Slack / Discord, mono caps)
 *   - truncated webhook URL (mono)
 *   - subscribed events (mono caps badges)
 *   - mini delivery log (last 5: ts / event / status / latency)
 *   - mute toggle, remove (Crane red on confirm only)
 *
 * Adding a channel uses an inline form with kind dropdown, URL input, and
 * a checkbox grid of events. Defaults match `INTEGRATION_EVENTS.defaultOn`.
 *
 * NOTE: uses only `integrations.*` procedures. Per-channel delivery history
 * is not available in the beta: `<DeliveryMini>` shows the last-known status
 * that `integrations.list` already returns, and nothing more.
 */

const EVENTS = [
  { value: "job.completed", defaultOn: true },
  { value: "job.failed", defaultOn: true },
  { value: "design.created", defaultOn: false },
  { value: "billing.upgraded", defaultOn: true },
  { value: "member.invited", defaultOn: false },
  { value: "usage.cap_warning", defaultOn: true },
  { value: "usage.cap_reached", defaultOn: true },
] as const;

type EventName = (typeof EVENTS)[number]["value"];
type Kind = "slack" | "discord";

interface ChannelRow {
  id: string;
  integrationId: string;
  webhookUrl: string;
  events: string[];
  muted: boolean;
  lastDeliveredAt?: string | Date | null;
  lastStatusCode?: number | null;
}

interface IntegrationRow {
  id: string;
  kind: Kind;
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

function truncate(url: string, head = 28, tail = 6): string {
  if (url.length <= head + tail + 3) return url;
  return `${url.slice(0, head)}…${url.slice(-tail)}`;
}

function statusTone(code?: number | null): string {
  if (code == null) return "border-lattice bg-paper-fold text-graphite-soft";
  if (code >= 200 && code < 300) return "border-lattice bg-paper text-ink";
  if (code >= 400 && code < 500)
    return "border-yellow-300 bg-yellow-50 text-yellow-800";
  return "border-crane/40 bg-crane-glow text-crane-deep";
}

export function IntegrationsPanel() {
  const utils = trpc.useUtils();
  const query = trpc.integrations.list.useQuery();
  const items = useMemo(() => coerceItems(query.data), [query.data]);

  const [adding, setAdding] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; message: string } | null>(
    null,
  );

  const notify = (m: { kind: "ok" | "err"; message: string }) => {
    setToast(m);
    setTimeout(() => setToast(null), 4000);
  };

  const update = trpc.integrations.updateChannel.useMutation({
    onSuccess: () => void utils.integrations.list.invalidate(),
    onError: (e) => notify({ kind: "err", message: e.message }),
  });
  const disconnect = trpc.integrations.disconnect.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
      setConfirmRemove(null);
      notify({ kind: "ok", message: "Integration disconnected." });
    },
    onError: (e) => notify({ kind: "err", message: e.message }),
  });

  return (
    <section className="space-y-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Chat
          </p>
          <h2 className="mt-1.5 font-display text-[22px] text-ink">
            Slack &amp; Discord
          </h2>
          <p className="mt-1.5 max-w-xl font-sans text-[13.5px] text-graphite">
            Forward job, billing, and usage events into a chat channel. Each
            row keeps its own event filter and mute state.
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="btn-primary"
          >
            <Plus className="h-4 w-4" /> Add channel
          </button>
        )}
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

      {adding && (
        <AddChannelForm
          onCancel={() => setAdding(false)}
          onSuccess={() => {
            setAdding(false);
            notify({ kind: "ok", message: "Channel connected." });
          }}
          onError={(m) => notify({ kind: "err", message: m })}
        />
      )}

      {query.isLoading ? (
        <div className="px-8 py-10 text-center font-sans text-[14px] text-graphite">
          Loading…
        </div>
      ) : items.length === 0 && !adding ? (
        <div className="px-8 py-10 text-center">
          <p className="font-sans text-[14px] text-graphite">
            No chat channels yet. Add one to start receiving events.
          </p>
        </div>
      ) : (
        <ul role="list" className="space-y-3">
          {items.flatMap((integ) =>
            integ.channels.map((ch) => (
              <li
                key={ch.id}
                className="bg-paper p-4 space-y-3"
              >
                <div className="flex flex-wrap items-start gap-3">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-lattice bg-paper-fold">
                    {integ.kind === "slack" ? (
                      <Slack className="h-4 w-4 text-ink" />
                    ) : (
                      <MessageSquare className="h-4 w-4 text-ink" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-sans text-[12px] rounded-full border border-lattice bg-paper-fold px-2 py-0.5 text-graphite">
                        {integ.kind}
                      </span>
                      <span className="font-sans text-[13px] text-ink">
                        {integ.name || `${integ.kind} channel`}
                      </span>
                      {ch.muted && (
                        <span className="font-sans text-[12px] rounded-full border border-yellow-300 bg-yellow-50 px-2 py-0.5 text-yellow-800">
                          muted
                        </span>
                      )}
                    </div>
                    <p
                      className="mt-1 font-mono text-[12px] text-graphite truncate"
                      title={ch.webhookUrl}
                    >
                      {truncate(ch.webhookUrl)}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {ch.events.length === 0 ? (
                        <span className="font-sans text-[12px] text-graphite-soft">
                          no events subscribed
                        </span>
                      ) : (
                        ch.events.map((ev) => (
                          <span
                            key={ev}
                            className="font-sans text-[12px] rounded-full border border-lattice bg-paper-fold px-2 py-0.5 text-graphite"
                          >
                            {ev}
                          </span>
                        ))
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() =>
                        update.mutate({ id: ch.id, muted: !ch.muted })
                      }
                      aria-pressed={ch.muted}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink"
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
                    {confirmRemove === integ.id ? (
                      <>
                        <button
                          type="button"
                          onClick={() => disconnect.mutate({ id: integ.id })}
                          disabled={disconnect.isPending}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-crane bg-crane px-3 py-1.5 font-sans text-[12px] text-paper hover:bg-crane-deep"
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmRemove(null)}
                          className="rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-graphite hover:border-ink"
                          aria-label="Cancel removal"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmRemove(integ.id)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink"
                        aria-label="Remove integration"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </div>
                <DeliveryMini fallback={ch} />
              </li>
            )),
          )}
        </ul>
      )}
    </section>
  );
}

// ─── Add channel form ──────────────────────────────────────────────────────

interface AddProps {
  onCancel: () => void;
  onSuccess: () => void;
  onError: (m: string) => void;
}

function AddChannelForm({ onCancel, onSuccess, onError }: AddProps) {
  const utils = trpc.useUtils();
  const [kind, setKind] = useState<Kind>("slack");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<Set<EventName>>(
    new Set(EVENTS.filter((e) => e.defaultOn).map((e) => e.value as EventName)),
  );

  const connect = trpc.integrations.connect.useMutation({
    onSuccess: () => {
      void utils.integrations.list.invalidate();
      onSuccess();
    },
    onError: (e) => onError(e.message),
  });

  const toggleEvent = (ev: EventName) => {
    setEvents((prev) => {
      const next = new Set(prev);
      if (next.has(ev)) next.delete(ev);
      else next.add(ev);
      return next;
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        connect.mutate({
          kind,
          name: name.trim(),
          webhookUrl: url.trim(),
          events: Array.from(events),
        });
      }}
      className="rounded-lg border border-lattice bg-paper p-5 space-y-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-display text-[16px] text-ink">Add channel</h3>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full border border-lattice p-1.5 text-graphite hover:border-ink hover:text-ink"
          aria-label="Cancel"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-[160px_1fr]">
        <label className="space-y-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            Kind
          </span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as Kind)}
            className="w-full rounded-xl border border-lattice bg-paper-fold px-3 py-2 font-sans text-[13px] text-ink"
          >
            <option value="slack">Slack</option>
            <option value="discord">Discord</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            Label (optional)
          </span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="#alerts"
            maxLength={120}
            className="w-full rounded-xl border border-lattice bg-paper-fold px-3 py-2 font-sans text-[13px] text-ink"
          />
        </label>
      </div>

      <label className="block space-y-1">
        <span className="font-sans text-[12px] text-graphite-soft">
          Webhook URL
        </span>
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={
            kind === "slack"
              ? "https://hooks.slack.com/services/T…/B…/…"
              : "https://discord.com/api/webhooks/…"
          }
          className="w-full rounded-xl border border-lattice bg-paper-fold px-3 py-2 font-mono text-[12px] text-ink"
        />
      </label>

      <fieldset className="space-y-2">
        <legend className="font-sans text-[12px] text-graphite-soft">
          Events
        </legend>
        <div className="grid gap-2 md:grid-cols-2">
          {EVENTS.map((e) => (
            <label
              key={e.value}
              className="inline-flex items-center gap-2 rounded-xl border border-lattice bg-paper-fold px-3 py-2"
            >
              <input
                type="checkbox"
                checked={events.has(e.value as EventName)}
                onChange={() => toggleEvent(e.value as EventName)}
                className="h-3.5 w-3.5 accent-ink"
              />
              <span className="font-sans text-[12px] text-ink">
                {e.value}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex items-center gap-3 pt-1">
        <button
          type="submit"
          disabled={connect.isPending || !url.trim()}
          className="btn-primary disabled:opacity-60"
        >
          {connect.isPending ? "Connecting…" : "Connect"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="font-sans text-[13px] text-graphite hover:text-ink"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ─── Mini delivery log (last 5) ────────────────────────────────────────────

/**
 * Per-channel status summary.
 *
 * A full mini delivery log needs `webhooks.deliveries`, which is not on the
 * router: so this shows only the last-known status fields that
 * `integrations.list` already returns.
 */
function DeliveryMini({ fallback }: { fallback: ChannelRow }) {
  return (
    <div className="px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-sans text-[12px] text-graphite-soft">
          Last delivery
        </span>
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 font-sans text-[12px]",
            statusTone(fallback.lastStatusCode),
          )}
        >
          {fallback.lastStatusCode ?? "N/A"}
        </span>
      </div>
      <p className="mt-1 font-mono text-[11px] text-graphite">
        {formatTs(fallback.lastDeliveredAt) || "no deliveries yet"}
      </p>
      <p className="mt-1 font-sans text-[11px] text-graphite-soft">
        Full delivery history arrives after the beta.
      </p>
    </div>
  );
}

function formatTs(d?: string | Date | null): string {
  if (!d) return "";
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default IntegrationsPanel;
