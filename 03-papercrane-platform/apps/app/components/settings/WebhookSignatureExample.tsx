"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

export interface WebhookSignatureExampleProps {
  /** Header name we sign requests with. Defaults to Paper Crane's. */
  signatureHeader?: string;
  /** Default language tab to render. */
  defaultLanguage?: "node" | "python";
}

const NODE_SNIPPET = `import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyPaperCrane(
  rawBody: string | Buffer,
  signatureHeader: string | undefined,
  secret: string,
): boolean {
  if (!signatureHeader) return false;

  // Header format: "t=<unix>,v1=<hex>"
  const parts = Object.fromEntries(
    signatureHeader.split(",").map((kv) => kv.split("=") as [string, string]),
  );
  if (!parts.t || !parts.v1) return false;

  // Reject anything older than 5 minutes to defeat replays.
  const ageSec = Math.abs(Date.now() / 1000 - Number(parts.t));
  if (Number.isNaN(ageSec) || ageSec > 300) return false;

  const signed = \`\${parts.t}.\${typeof rawBody === "string" ? rawBody : rawBody.toString("utf8")}\`;
  const expected = createHmac("sha256", secret).update(signed).digest("hex");

  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(parts.v1, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}`;

const PY_SNIPPET = `import hmac, hashlib, time

def verify_papercrane(raw_body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False

    parts = dict(kv.split("=", 1) for kv in signature_header.split(","))
    if "t" not in parts or "v1" not in parts:
        return False

    # Reject anything older than 5 minutes to defeat replays.
    if abs(time.time() - int(parts["t"])) > 300:
        return False

    signed = f"{parts['t']}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`;

/**
 * Drop-in code-snippet card showing the canonical HMAC verification recipe
 * for Paper Crane webhooks. Two language tabs (Node, Python): both use
 * constant-time comparison and reject stale timestamps to defeat replays.
 *
 * The snippet is intentionally framework-agnostic: callers paste it into
 * their own request handler and pass the raw body + header.
 */
export function WebhookSignatureExample({
  signatureHeader = "Paper-Crane-Signature",
  defaultLanguage = "node",
}: WebhookSignatureExampleProps) {
  const [lang, setLang] = useState<"node" | "python">(defaultLanguage);
  const [copied, setCopied] = useState(false);

  const snippet = lang === "node" ? NODE_SNIPPET : PY_SNIPPET;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // user can still triple-click select
    }
  };

  return (
    <section className="overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-5 py-3">
        <div>
          <h3 className="font-display text-[16px] text-ink">
            Verify the signature
          </h3>
          <p className="mt-0.5 font-sans text-[12px] text-graphite-soft">
            We sign each request with HMAC-SHA256 and the{" "}
            <code className="font-mono text-[11px] text-ink">{signatureHeader}</code>{" "}
            header. Reject anything older than 5 minutes.
          </p>
        </div>
        <div
          role="tablist"
          aria-label="Language"
          className="inline-flex rounded-full bg-paper p-0.5 font-sans text-[12px]"
        >
          {(["node", "python"] as const).map((l) => (
            <button
              key={l}
              role="tab"
              aria-selected={lang === l}
              onClick={() => setLang(l)}
              type="button"
              className={
                lang === l
                  ? "rounded-full bg-ink px-3 py-1 text-paper"
                  : "rounded-full px-3 py-1 text-graphite hover:text-ink transition-colors"
              }
            >
              {l}
            </button>
          ))}
        </div>
      </header>

      <div className="relative">
        <pre className="overflow-x-auto bg-paper px-5 py-4 font-mono text-[12px] leading-relaxed text-ink">
          {snippet}
        </pre>
        <button
          type="button"
          onClick={copy}
          aria-label="Copy snippet"
          className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper-fold px-3 py-1 font-sans text-[12px] text-ink hover:border-ink transition-colors"
        >
          {copied ? (
            <Check className="h-3 w-3" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </section>
  );
}

export default WebhookSignatureExample;
