import Link from "next/link";
import type { MDXComponents } from "mdx/types";
import { TOOLS, type ToolEntry } from "@/lib/tools";

function ToolCard({ id }: { id: string }) {
  const t = TOOLS.find((x) => x.id === id);
  if (!t) return null;
  return (
    <Link
      href={`/tools/${t.id}`}
      className="not-prose block rounded-2xl border border-lattice-strong bg-paper-fold/50 p-5 transition-colors hover:border-ink hover:bg-paper-fold"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="font-display text-[22px] tracking-tight text-ink">{t.name}</div>
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-graphite">
          {t.tier}
        </span>
      </div>
      <p className="mt-1 text-[14px] text-ink-soft">{t.blurb}</p>
      <div className="mt-3 flex flex-wrap gap-3 font-mono text-[11px] text-graphite">
        <span>{t.category.replace(/_/g, " ")}</span>
        <span>· {t.gpu}</span>
        <span>· ~{t.estSeconds}s/design</span>
      </div>
    </Link>
  );
}

function ToolGrid({ ids }: { ids?: string[] }) {
  const list: ToolEntry[] = ids ? ids.map((id) => TOOLS.find((t) => t.id === id)!).filter(Boolean) : TOOLS;
  return (
    <div className="not-prose mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {list.map((t) => (
        <ToolCard key={t.id} id={t.id} />
      ))}
    </div>
  );
}

function Callout({
  variant = "note",
  children,
}: {
  variant?: "note" | "warn" | "tip";
  children: React.ReactNode;
}) {
  const styles =
    variant === "warn"
      ? "border-crane/40 bg-crane-glow"
      : variant === "tip"
        ? "border-ink/30 bg-paper-fold"
        : "border-lattice-strong bg-paper-fold/60";
  const label = variant === "warn" ? "Warning" : variant === "tip" ? "Tip" : "Note";
  return (
    <aside className={`not-prose my-5 rounded-xl border px-4 py-3 ${styles}`}>
      <div className="eyebrow mb-1 text-graphite">{label}</div>
      <div className="text-[14px] text-ink-soft">{children}</div>
    </aside>
  );
}

export const mdxComponents: MDXComponents = {
  h1: (props) => <h1 className="font-display text-[44px] leading-[1.05] tracking-tight text-ink" {...props} />,
  h2: (props) => (
    <h2
      className="mt-12 scroll-mt-24 font-display text-[28px] tracking-tight text-ink"
      {...props}
    />
  ),
  h3: (props) => (
    <h3 className="mt-8 scroll-mt-24 font-display text-[20px] tracking-tight text-ink" {...props} />
  ),
  p: (props) => <p className="mt-4 text-[15.5px] leading-7 text-ink-soft" {...props} />,
  a: (props) => <a className="text-crane underline-offset-4 hover:underline" {...props} />,
  ul: (props) => <ul className="mt-4 ml-5 list-disc space-y-1.5 text-[15.5px] text-ink-soft" {...props} />,
  ol: (props) => <ol className="mt-4 ml-5 list-decimal space-y-1.5 text-[15.5px] text-ink-soft" {...props} />,
  li: (props) => <li className="leading-7" {...props} />,
  code: ({ className, ...props }) => (
    <code
      className={`rounded bg-paper-fold px-1.5 py-0.5 font-mono text-[13px] text-ink ${className ?? ""}`}
      {...props}
    />
  ),
  pre: (props) => (
    <pre
      className="mt-5 overflow-x-auto rounded-xl border border-lattice-strong bg-ink p-4 font-mono text-[13px] leading-6 text-paper"
      {...props}
    />
  ),
  table: (props) => (
    <div className="not-prose mt-5 overflow-x-auto rounded-xl border border-lattice-strong">
      <table className="w-full text-[14px]" {...props} />
    </div>
  ),
  th: (props) => (
    <th
      className="border-b border-lattice-strong bg-paper-fold px-3 py-2 text-left font-mono text-[11px] uppercase tracking-[0.18em] text-graphite"
      {...props}
    />
  ),
  td: (props) => <td className="border-b border-lattice px-3 py-2 text-ink-soft" {...props} />,
  hr: () => <hr className="my-10 border-lattice" />,
  blockquote: (props) => (
    <blockquote
      className="mt-5 border-l-2 border-crane bg-paper-fold/40 px-4 py-2 text-[15px] italic text-ink-soft"
      {...props}
    />
  ),
  ToolCard,
  ToolGrid,
  Callout,
};
