"use client";

import { useState } from "react";
import { Cpu, PlugZap, Trash2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

export function ModalConnect() {
  const utils = trpc.useUtils();
  const status = trpc.modalAccounts.status.useQuery();
  const [tokenId, setTokenId] = useState("");
  const [tokenSecret, setTokenSecret] = useState("");
  const [environment, setEnvironment] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const connect = trpc.modalAccounts.connect.useMutation({
    onSuccess: async () => {
      setTokenId("");
      setTokenSecret("");
      await utils.modalAccounts.status.invalidate();
      setMessage({
        kind: "ok",
        text: "Modal connected. Paper Crane will provision each missing tool app once on first use, then reuse the deployed function.",
      });
    },
    onError: (e) => setMessage({ kind: "err", text: e.message }),
  });

  const disconnect = trpc.modalAccounts.disconnect.useMutation({
    onSuccess: async () => {
      await utils.modalAccounts.status.invalidate();
      setMessage({ kind: "ok", text: "Modal disconnected. Jobs fall back to preview mode when no system credentials are configured." });
    },
    onError: (e) => setMessage({ kind: "err", text: e.message }),
  });

  const connected = Boolean(status.data?.connected);
  const busy = connect.isPending || disconnect.isPending;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    if (!/^ak-[A-Za-z0-9._-]{8,}$/.test(tokenId.trim()) || !/^as-[A-Za-z0-9._-]{8,}$/.test(tokenSecret.trim())) {
      setMessage({ kind: "err", text: "Use the paired ak- token ID and as- token secret from Modal." });
      return;
    }
    connect.mutate({
      tokenId: tokenId.trim(),
      tokenSecret: tokenSecret.trim(),
      environment: environment.trim() || undefined,
    });
  }

  return (
    <section className="space-y-5 bg-paper p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-lattice bg-paper-fold">
            <Cpu className="h-5 w-5 text-ink" />
          </span>
          <div>
            <h2 className="font-display text-[20px] text-ink">Modal compute</h2>
            <p className="mt-1 max-w-2xl font-sans text-[13px] text-graphite">
              Bring your own Modal token so protein design jobs run on your
              workspace instead of the local preview runner.
            </p>
          </div>
        </div>
        <span
          className={cn(
            "rounded-full border px-3 py-1 font-sans text-[12px]",
            connected
              ? "border-ink bg-ink text-paper"
              : "border-lattice bg-paper-fold text-graphite",
          )}
        >
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>

      {connected && (
        <div className="px-4 py-3 font-sans text-[13px] text-graphite">
          <p className="text-ink">
            Token ending in{" "}
            <span className="font-mono">...{status.data?.tokenIdSuffix}</span>
            {status.data?.environment ? (
              <> in <span className="font-mono">{status.data.environment}</span></>
            ) : null}
            .
          </p>
          <p className="mt-1 text-[12px] text-graphite-soft">
            Update the form below to rotate credentials. The secret is never
            shown again after saving.
          </p>
        </div>
      )}

      <form onSubmit={onSubmit} className="grid gap-4 md:grid-cols-3">
        <label className="block">
          <span className="block font-sans text-[12px] text-graphite-soft">
            Token ID
          </span>
          <input
            type="password"
            value={tokenId}
            onChange={(e) => setTokenId(e.target.value)}
            placeholder="ak-..."
            autoComplete="off"
            required
            className="mt-2 w-full rounded-lg border border-lattice bg-paper px-4 py-2.5 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="block font-sans text-[12px] text-graphite-soft">
            Token secret
          </span>
          <input
            type="password"
            value={tokenSecret}
            onChange={(e) => setTokenSecret(e.target.value)}
            placeholder="as-..."
            autoComplete="off"
            required
            className="mt-2 w-full rounded-lg border border-lattice bg-paper px-4 py-2.5 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="block font-sans text-[12px] text-graphite-soft">
            Environment
          </span>
          <input
            type="text"
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
            placeholder="main (optional)"
            autoComplete="off"
            className="mt-2 w-full rounded-lg border border-lattice bg-paper px-4 py-2.5 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>
        <div className="flex flex-wrap gap-2 md:col-span-3">
          <button type="submit" disabled={busy} className="btn-primary inline-flex items-center gap-2">
            <PlugZap className="h-4 w-4" />
            {connect.isPending ? "Connecting..." : connected ? "Update Modal" : "Connect Modal"}
          </button>
          {connected && (
            <button
              type="button"
              disabled={busy}
              onClick={() => disconnect.mutate()}
              className="inline-flex items-center gap-2 rounded-full border border-lattice px-4 py-2 font-sans text-[13px] text-graphite hover:border-crane hover:text-crane-deep disabled:opacity-60"
            >
              <Trash2 className="h-4 w-4" />
              Disconnect
            </button>
          )}
        </div>
      </form>

      {message && (
        <div
          role={message.kind === "err" ? "alert" : "status"}
          className={cn(
            "rounded-lg border px-4 py-3 font-sans text-[13px]",
            message.kind === "ok"
              ? "border-lattice bg-paper-fold text-ink"
              : "border-crane/40 bg-crane-glow text-crane-deep",
          )}
        >
          {message.text}
        </div>
      )}
    </section>
  );
}

export default ModalConnect;
