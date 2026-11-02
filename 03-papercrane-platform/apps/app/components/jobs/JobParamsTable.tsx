"use client";

import { useState } from "react";
import { Check, Copy, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

interface JobParamsTableProps {
  params: Record<string, unknown> | null | undefined;
  toolChainFallback?: string[];
  className?: string;
}

export function JobParamsTable({
  params,
  toolChainFallback,
  className,
}: JobParamsTableProps) {
  if (!params) {
    return (
      <p className={cn("font-sans text-[13px] text-graphite", className)}>
        No parameters recorded for this job.
      </p>
    );
  }

  const req = (params.request && typeof params.request === "object" ? params.request : params) as Record<string, unknown>;
  const rows: Array<[string, string]> = [];
  const chain = Array.isArray(req.toolChain) ? req.toolChain : toolChainFallback;
  if (chain?.length) rows.push(["Tool", chain.join(" → ")]);
  const labels: Record<string, string> = { targetPdb: "Input backbone", targetChain: "Target chain", numDesigns: "Designs requested", seed: "Seed", seeds: "Seeds", lengthRange: "Length range", hotspots: "Hotspots" };
  for (const [key, label] of Object.entries(labels)) {
    const value = req[key];
    if (value == null || value === "" || (Array.isArray(value) && !value.length)) continue;
    rows.push([label, typeof value === "object" ? JSON.stringify(value) : String(value)]);
  }
  const toolParams = req.toolParams;
  if (toolParams && typeof toolParams === "object") {
    for (const [key, value] of Object.entries(toolParams)) {
      if (value == null || ["projectId", "targetId"].includes(key)) continue;
      if (["string", "number", "boolean"].includes(typeof value)) rows.push([key.replace(/_/g, " "), String(value)]);
    }
  }
  return (
    <section aria-label="Job parameters" className={cn("space-y-4", className)}>
      <h2 className="text-sm font-medium text-ink">Parameters</h2>
      <dl className="divide-y divide-lattice bg-paper">
        {rows.map(([label, value]) => <Row key={label} label={label} value={value}><span className="break-all font-mono text-xs text-ink">{value}</span></Row>)}
      </dl>

      <RawJsonViewer params={params} />
    </section>
  );
}

function RawJsonViewer({ params }: { params: unknown }) {
  const [copied, setCopied] = useState(false);
  const json = safeStringify(params);
  const onCopy = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };
  return (
    <details className="group rounded-lg border border-lattice bg-paper">
      <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-3 font-sans text-[12px] text-graphite hover:text-ink">
        <span className="flex items-center gap-2">
          <ChevronRight className="w-3.5 h-3.5 transition-transform group-open:rotate-90" />
          Raw JSON
        </span>
        <button
          type="button"
          onClick={onCopy}
          aria-label="Copy raw JSON"
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-lattice bg-paper-fold/60 px-2 py-1 font-sans text-[12px] hover:border-ink hover:text-ink",
            copied ? "text-ink" : "text-graphite",
          )}
        >
          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </summary>
      <pre className="px-4 pb-4 overflow-x-auto font-mono text-[11px] leading-relaxed">
        {tintJson(json)}
      </pre>
    </details>
  );
}

/**
 * Lightweight JSON syntax tint: keys/strings/numbers/booleans rendered in
 * graphite shades against ink. Editorial, not a code-IDE rainbow.
 */
function tintJson(json: string): React.ReactNode {
  // Tokenise: keys ("foo":), strings, numbers, booleans/null, punctuation.
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([{}\[\],])/g;
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(json)) !== null) {
    if (m.index > last) {
      out.push(<span key={key++} className="text-ink">{json.slice(last, m.index)}</span>);
    }
    const [tok, str, colon, kw, num, punct] = m;
    if (str && colon) {
      out.push(<span key={key++} className="text-graphite-soft">{str}</span>);
      out.push(<span key={key++} className="text-graphite">{colon}</span>);
    } else if (str) {
      out.push(<span key={key++} className="text-ink">{str}</span>);
    } else if (kw) {
      out.push(<span key={key++} className="text-graphite italic">{kw}</span>);
    } else if (num) {
      out.push(<span key={key++} className="text-graphite">{num}</span>);
    } else if (punct) {
      out.push(<span key={key++} className="text-graphite-soft">{punct}</span>);
    } else {
      out.push(<span key={key++}>{tok}</span>);
    }
    last = m.index + tok.length;
  }
  if (last < json.length) {
    out.push(<span key={key++} className="text-ink">{json.slice(last)}</span>);
  }
  return out;
}

interface RowProps {
  label: string;
  value: string | null;
  children: React.ReactNode;
}

function Row({ label, value, children }: RowProps) {
  const [copied, setCopied] = useState(false);
  const canCopy = value != null && value.length > 0;
  const onCopy = async () => {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(value!);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable in some browsers; silently ignore.
    }
  };
  return (
    <div className="px-4 py-3 grid grid-cols-[100px_1fr_auto] sm:grid-cols-[140px_1fr_auto] gap-4 items-start">
      <dt className="font-sans text-[12px] text-graphite-soft pt-0.5">
        {label}
      </dt>
      <dd className="min-w-0">{children}</dd>
      <button
        type="button"
        onClick={onCopy}
        disabled={!canCopy}
        aria-label={`Copy ${label}`}
        className={cn(
          "inline-flex items-center gap-1 rounded-md border px-2 py-1 font-sans text-[12px] transition-colors",
          canCopy
            ? "border-lattice bg-paper text-graphite hover:text-ink hover:border-ink"
            : "border-lattice bg-paper-fold text-graphite-soft cursor-not-allowed",
        )}
      >
        {copied ? (
          <>
            <Check className="w-3 h-3" /> Copied
          </>
        ) : (
          <>
            <Copy className="w-3 h-3" /> Copy
          </>
        )}
      </button>
    </div>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
