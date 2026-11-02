"use client";

import { FormEvent, useState } from "react";
import { ArrowUpRight } from "lucide-react";

export function SubmitForm() {
  const [email, setEmail] = useState("");
  const [tool, setTool] = useState("");
  const [repo, setRepo] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const subject = encodeURIComponent(`Benchmark submission · ${tool || "new tool"}`);
    const body = encodeURIComponent(
      `Tool name: ${tool}\nRepo / paper: ${repo}\nContact email: ${email}\n\nPlease send the benchmark protocol and target inputs.`
    );
    window.location.href = `mailto:benchmark@papercrane.bio?subject=${subject}&body=${body}`;
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="hairline-border bg-paper rounded-sm p-6 md:p-8 space-y-4"
    >
      <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite mb-2">
        Submission form
      </div>

      <Field label="Tool name" id="tool">
        <input
          id="tool"
          required
          value={tool}
          onChange={(e) => setTool(e.target.value)}
          placeholder="e.g. CraneDiffusion"
          className="input-bare"
        />
      </Field>

      <Field label="Repo or paper URL" id="repo">
        <input
          id="repo"
          required
          type="url"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          placeholder="https://github.com/your-lab/your-tool"
          className="input-bare"
        />
      </Field>

      <Field label="Contact email" id="email">
        <input
          id="email"
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
        className="mt-4 inline-flex w-full items-center justify-center gap-2 bg-ink text-paper rounded-full py-3.5 font-sans text-[15px] tracking-tight hover:bg-crane transition-all group"
      >
        Submit to leaderboard
        <ArrowUpRight
          className="w-4 h-4 group-hover:rotate-45 transition-transform duration-500"
          strokeWidth={1.8}
        />
      </button>

      <div className="font-mono text-[10px] tracking-[0.18em] uppercase text-graphite-soft pt-2">
        Opens your email client · benchmark@papercrane.bio
      </div>

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
