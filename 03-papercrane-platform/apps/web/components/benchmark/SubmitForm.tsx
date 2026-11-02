"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowUpRight, Check } from "lucide-react";

type Status = "idle" | "submitting" | "success" | "error";

export function SubmitForm() {
  const [email, setEmail]   = useState("");
  const [name, setName]     = useState("");
  const [github, setGithub] = useState("");
  const [paper, setPaper]   = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [showToast, setShowToast] = useState(false);

  useEffect(() => {
    if (status !== "success") return;
    setShowToast(true);
    const t = setTimeout(() => setShowToast(false), 4500);
    return () => clearTimeout(t);
  }, [status]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus("submitting");
    try {
      // Best-effort: hit the optional collector API. Falls back to mailto.
      try {
        await fetch("/api/benchmark-submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, name, github, paper }),
        });
      } catch {
        // Ignore — we'll still confirm success and use mailto fallback below.
      }
      setStatus("success");
      // Mailto fallback so a real human gets pinged.
      const subject = encodeURIComponent(`Benchmark submission · ${name || "new tool"}`);
      const body = encodeURIComponent(
        `Tool name: ${name}\nGitHub: ${github}\nPaper: ${paper}\nContact email: ${email}\n\nPlease send the benchmark protocol and target inputs.`,
      );
      // Open mail client in a new tab so the form state is preserved.
      const url = `mailto:benchmark@papercrane.bio?subject=${subject}&body=${body}`;
      window.open(url, "_blank");
      // Clear inputs.
      setEmail("");
      setName("");
      setGithub("");
      setPaper("");
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className="relative">
      <form
        onSubmit={handleSubmit}
        className="hairline-border bg-paper rounded-sm p-6 md:p-8 space-y-4"
      >
        <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite mb-2">
          Submission form
        </div>

        <Field label="Tool / model name" id="bench-name">
          <input
            id="bench-name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CraneDiffusion v0.2"
            className="input-bare"
          />
        </Field>

        <Field label="GitHub URL" id="bench-github">
          <input
            id="bench-github"
            required
            type="url"
            value={github}
            onChange={(e) => setGithub(e.target.value)}
            placeholder="https://github.com/your-lab/your-tool"
            className="input-bare"
          />
        </Field>

        <Field label="Paper / preprint URL" id="bench-paper">
          <input
            id="bench-paper"
            type="url"
            value={paper}
            onChange={(e) => setPaper(e.target.value)}
            placeholder="https://arxiv.org/abs/…  (optional)"
            className="input-bare"
          />
        </Field>

        <Field label="Contact email" id="bench-email">
          <input
            id="bench-email"
            required
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@lab.edu"
            className="input-bare"
          />
        </Field>

        <button
          type="submit"
          disabled={status === "submitting"}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 bg-ink text-paper rounded-full py-3.5 font-sans text-[15px] tracking-tight hover:bg-crane transition-all group disabled:opacity-60 disabled:cursor-wait"
        >
          {status === "submitting" ? "Submitting…" : "Submit to leaderboard"}
          <ArrowUpRight
            className="w-4 h-4 group-hover:rotate-45 transition-transform duration-500"
            strokeWidth={1.8}
          />
        </button>

        <div className="font-mono text-[10px] tracking-[0.18em] uppercase text-graphite-soft pt-2">
          Reviewed weekly · benchmark@papercrane.bio
        </div>

        {status === "error" && (
          <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-crane pt-2">
            Something went wrong. Email us directly at benchmark@papercrane.bio.
          </div>
        )}

        <style>{`
          .input-bare {
            width: 100%;
            background: transparent;
            border: none;
            border-bottom: 1px solid rgba(20,17,13,0.18);
            padding: 12px 0;
            font-family: var(--font-instrument);
            font-size: 16px;
            color: #14110D;
            outline: none;
            transition: border-color 0.2s;
          }
          .input-bare::placeholder { color: #8A857B; }
          .input-bare:focus { border-bottom-color: #C1272D; }
        `}</style>
      </form>

      {/* Toast */}
      <div
        aria-live="polite"
        className={
          "fixed bottom-6 left-1/2 -translate-x-1/2 z-50 transition-all duration-300 " +
          (showToast ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3 pointer-events-none")
        }
      >
        <div className="hairline-border bg-ink text-paper rounded-full px-5 py-3 flex items-center gap-3 shadow-lg">
          <span className="bg-crane rounded-full w-5 h-5 flex items-center justify-center">
            <Check className="w-3 h-3 text-paper" strokeWidth={3} />
          </span>
          <span className="font-sans text-[14px]">
            Thanks — we&rsquo;ll be in touch within a week.
          </span>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
