"use client";

import { useState, FormEvent } from "react";

type Status = "idle" | "submitting" | "success" | "error";

export default function BetaSignupForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [email, setEmail] = useState("");
  const [org, setOrg] = useState("");
  const [useCase, setUseCase] = useState("");
  const [target, setTarget] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setStatus("submitting");
    setErrorMsg("");

    try {
      const res = await fetch("/api/beta-signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, org, useCase, target }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setErrorMsg(data?.error || "REQUEST FAILED");
        setStatus("error");
        return;
      }

      setStatus("success");
    } catch {
      setErrorMsg("NETWORK ERROR");
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div className="border-t border-b border-ink/20 py-12 px-6 text-center">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink/60 mb-3">
          Thank you
        </p>
        <h3 className="font-serif text-2xl text-ink mb-2">
          You&apos;re on the list.
        </h3>
        <p className="font-sans text-sm text-ink/70">
          We&apos;ll reach out within 48 hours.
        </p>
      </div>
    );
  }

  const labelCls =
    "block font-mono text-[10px] uppercase tracking-[0.2em] text-ink/60 mb-2";
  const inputCls =
    "w-full bg-transparent border-0 border-b border-ink/30 px-0 py-2 font-sans text-sm text-ink placeholder:text-ink/30 focus:outline-none focus:border-ink transition-colors";

  return (
    <form onSubmit={handleSubmit} className="space-y-8" noValidate>
      <div>
        <label htmlFor="beta-email" className={labelCls}>
          Email <span className="text-[#C1272D]">*</span>
        </label>
        <input
          id="beta-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@lab.edu"
          className={inputCls}
          autoComplete="email"
        />
      </div>

      <div>
        <label htmlFor="beta-org" className={labelCls}>
          Organization / Lab
        </label>
        <input
          id="beta-org"
          type="text"
          value={org}
          onChange={(e) => setOrg(e.target.value)}
          placeholder="Stanford Bioengineering"
          className={inputCls}
          autoComplete="organization"
        />
      </div>

      <div>
        <label htmlFor="beta-target" className={labelCls}>
          Source Target
        </label>
        <input
          id="beta-target"
          type="text"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="PD-L1, RBD, etc."
          className={inputCls}
        />
      </div>

      <div>
        <label htmlFor="beta-usecase" className={labelCls}>
          Use Case
        </label>
        <textarea
          id="beta-usecase"
          rows={3}
          value={useCase}
          onChange={(e) => setUseCase(e.target.value)}
          placeholder="What are you designing, and why?"
          className={`${inputCls} resize-none`}
        />
      </div>

      {status === "error" && (
        <p
          role="alert"
          className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#C1272D]"
        >
          {errorMsg}
        </p>
      )}

      <div className="pt-4">
        <button
          type="submit"
          disabled={status === "submitting"}
          className="font-mono text-[11px] uppercase tracking-[0.22em] bg-ink text-paper px-8 py-3 hover:bg-ink/85 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {status === "submitting" ? "Submitting…" : "Request Access"}
        </button>
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink/40 mt-4">
          Beta cohort · Limited spots
        </p>
      </div>
    </form>
  );
}
