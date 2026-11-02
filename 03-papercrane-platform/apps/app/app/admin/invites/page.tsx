"use client";

import { Copy, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { trpc } from "@/lib/trpc/client";

/**
 * Admin invite-code dashboard.
 *
 * Two surfaces in one page:
 *   1. Generator form: choose count, max-uses, optional expiry + note,
 *      hit "Mint codes". Returned codes are displayed once with a
 *      copy-to-clipboard button. Admins are expected to copy them out
 *      of the page; we never email them.
 *   2. Recent codes table: the caller's own history (`listMyInvites`),
 *      with usage counter and expiry.
 *
 * Access control is enforced server-side by `assertBetaAdmin` inside
 * the tRPC router. This page is also gated client-side: if the
 * `listMyInvites` query 403s we render a friendly explainer instead
 * of an empty table so non-admins who guess the URL get useful copy.
 */
export default function AdminInvitesPage() {
  const list = trpc.beta.listMyInvites.useQuery();
  const generate = trpc.beta.generateInvite.useMutation();

  const [count, setCount] = useState(5);
  const [maxUses, setMaxUses] = useState(1);
  const [expiresInDays, setExpiresInDays] = useState<number | "">("");
  const [note, setNote] = useState("");
  // Codes minted *this session*, surfaced at the top of the page so the
  // admin can copy them before they refresh and only the table is left.
  const [freshCodes, setFreshCodes] = useState<
    { code: string; maxUses: number; expiresAt: string | null }[]
  >([]);
  const [query, setQuery] = useState("");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const isForbidden =
    list.error?.data && "code" in list.error.data && list.error.data.code === "FORBIDDEN";

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    const res = await generate.mutateAsync({
      count,
      maxUses,
      expiresInDays: expiresInDays === "" ? undefined : Number(expiresInDays),
      note: note.trim() || undefined,
    });
    setFreshCodes(
      res.codes.map((c) => ({
        code: c.code,
        maxUses: c.maxUses,
        expiresAt: c.expiresAt,
      })),
    );
    list.refetch();
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedCode(text);
      setTimeout(() => setCopiedCode((c) => (c === text ? null : c)), 1100);
    } catch {
      // Clipboard blocked (e.g. iframe / no permission). Selection is
      // fine to fall back on; users can ⌘C manually.
    }
  }

  const filteredCodes = useMemo(() => {
    const all = list.data?.codes ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (c) =>
        c.code.toLowerCase().includes(q) ||
        (c.note ?? "").toLowerCase().includes(q),
    );
  }, [list.data?.codes, query]);

  if (isForbidden) {
    return (
      <main className="mx-auto w-full max-w-2xl px-4 py-10 text-ink">
        <h1 className="font-mono text-[13px] uppercase tracking-[0.16em] text-ink">
          forbidden · 403
        </h1>
        <p className="mt-3 max-w-prose font-sans text-[13px] text-ink/70">
          You need admin or owner permissions to manage beta invite codes.
          Talk to whoever onboarded you.
        </p>
        <Link
          href="/app"
          className="mt-5 inline-block font-mono text-[12px] text-ink underline decoration-lattice-strong underline-offset-2"
        >
          ← back to dashboard
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8 text-ink">
      <header className="mb-5 flex items-baseline gap-3">
        <h1 className="font-mono text-[13px] uppercase tracking-[0.16em] text-ink">
          invites
        </h1>
        <span className="font-mono text-[11px] text-ink/50">
          {list.data?.codes?.length ?? 0} total · PC-XXXX-XXXX
        </span>
      </header>

      {/* Generator */}
      <section className="rounded-lg border border-lattice bg-paper p-3">
        <h2 className="font-mono text-[11px] uppercase tracking-wide text-ink/60">
          mint codes
        </h2>
        <form
          onSubmit={handleGenerate}
          className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4"
        >
          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
              How many
            </span>
            <input
              type="number"
              min={1}
              max={100}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="rounded border border-lattice bg-paper px-2 py-1 font-mono text-[12.5px] text-ink"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
              Max uses (0=∞)
            </span>
            <input
              type="number"
              min={0}
              max={10000}
              value={maxUses}
              onChange={(e) => setMaxUses(Number(e.target.value))}
              className="rounded border border-lattice bg-paper px-2 py-1 font-mono text-[12.5px] text-ink"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
              Expires in (days)
            </span>
            <input
              type="number"
              min={1}
              max={365}
              value={expiresInDays}
              onChange={(e) =>
                setExpiresInDays(e.target.value === "" ? "" : Number(e.target.value))
              }
              placeholder="never"
              className="rounded border border-lattice bg-paper px-2 py-1 font-mono text-[12.5px] text-ink placeholder:text-ink/40"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
              Note
            </span>
            <input
              type="text"
              maxLength={120}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="YC W26 dinner"
              className="rounded border border-lattice bg-paper px-2 py-1 font-sans text-[12.5px] text-ink placeholder:text-ink/40"
            />
          </label>

          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={generate.isPending}
              className="inline-flex items-center gap-1.5 rounded border border-ink bg-ink px-3 py-1.5 font-mono text-[12px] text-paper hover:bg-ink/90 disabled:opacity-60"
            >
              <Plus className="h-3.5 w-3.5" />
              {generate.isPending ? "minting…" : `mint ${count}`}
            </button>
          </div>
        </form>
      </section>

      {/* Fresh codes: shown once, this session only */}
      {freshCodes.length > 0 && (
        <section className="mt-4 rounded-lg border border-lattice bg-paper-fold/40 p-3">
          <div className="flex items-baseline justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-wide text-ink/70">
              just minted · {freshCodes.length}
            </h3>
            <span className="font-mono text-[10.5px] text-ink/50">
              copy now: shown once
            </span>
          </div>
          <ul className="mt-2 flex flex-col gap-1">
            {freshCodes.map((c) => (
              <li
                key={c.code}
                className="flex items-center justify-between gap-3 rounded border border-lattice bg-paper px-2.5 py-1.5"
              >
                <span className="font-mono text-[13px] tracking-wider text-ink">
                  {c.code}
                </span>
                <button
                  type="button"
                  onClick={() => copy(c.code)}
                  className="inline-flex items-center gap-1 rounded border border-lattice bg-paper-fold/40 px-2 py-0.5 font-mono text-[10.5px] text-ink/70 hover:border-ink/30 hover:text-ink"
                >
                  <Copy className="h-3 w-3" />
                  {copiedCode === c.code ? "copied" : "copy"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Recent table */}
      <section className="mt-6">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 className="font-mono text-[11px] uppercase tracking-wide text-ink/60">
            your codes
          </h2>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="filter by code or note…"
            className="w-56 rounded border border-lattice bg-paper px-2 py-1 font-sans text-[12px] text-ink placeholder:text-ink/40"
          />
        </div>
        {list.isLoading ? (
          <div className="rounded-lg border border-lattice bg-paper px-3 py-6 text-center font-sans text-[12.5px] text-ink/60">
            Loading…
          </div>
        ) : list.data && filteredCodes.length > 0 ? (
          <div className="overflow-hidden rounded-lg border border-lattice bg-paper">
            <table className="w-full text-left font-sans text-[12.5px]">
              <thead className="border-b border-lattice bg-paper-fold/50 text-[11px] uppercase tracking-wide text-ink/60">
                <tr>
                  <th className="px-3 py-2 font-normal">Code</th>
                  <th className="px-3 py-2 font-normal">Used</th>
                  <th className="px-3 py-2 font-normal">Cap</th>
                  <th className="px-3 py-2 font-normal">Expires</th>
                  <th className="px-3 py-2 font-normal">Note</th>
                </tr>
              </thead>
              <tbody>
                {filteredCodes.map((c) => {
                  const expired =
                    c.expiresAt && new Date(c.expiresAt).getTime() < Date.now();
                  const exhausted = c.maxUses !== 0 && c.usedCount >= c.maxUses;
                  return (
                    <tr
                      key={c.id}
                      className="border-b border-lattice/60 hover:bg-paper-fold/40"
                    >
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => copy(c.code)}
                          title={`Copy ${c.code}`}
                          className="rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-[12.5px] tracking-wider text-ink hover:border-lattice hover:bg-paper-fold/50"
                        >
                          {copiedCode === c.code ? "copied" : c.code}
                        </button>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-ink/80">
                        {c.usedCount}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-ink/80">
                        {c.maxUses === 0 ? "∞" : c.maxUses}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-ink/70">
                        {c.expiresAt
                          ? new Date(c.expiresAt).toLocaleDateString()
                          : "never"}
                        {expired && (
                          <span className="ml-1.5 rounded border border-lattice bg-paper-fold/60 px-1 py-0 font-mono text-[10px] uppercase text-ink/60">
                            expired
                          </span>
                        )}
                        {!expired && exhausted && (
                          <span className="ml-1.5 rounded border border-lattice bg-paper-fold/60 px-1 py-0 font-mono text-[10px] uppercase text-ink/60">
                            full
                          </span>
                        )}
                      </td>
                      <td className="max-w-[260px] truncate px-3 py-1.5 text-ink/70">
                        {c.note ?? ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : list.data && list.data.codes.length > 0 ? (
          <div className="rounded-lg border border-lattice bg-paper px-3 py-6 text-center font-sans text-[12.5px] text-ink/60">
            No codes match “{query}”.
          </div>
        ) : (
          <div className="rounded-lg border border-lattice bg-paper px-3 py-6 text-center font-sans text-[12.5px] text-ink/60">
            No codes yet: mint some above.
          </div>
        )}
      </section>
    </main>
  );
}
