import { notFound } from "next/navigation";
import Link from "next/link";
import { TOOLS, TOOL_SLUGS, toolBySlug } from "@/lib/tools";
import { mdxComponents } from "@/components/MdxComponents";

type Params = Promise<{ slug: string }>;

export function generateStaticParams() {
  return TOOL_SLUGS.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: { params: Params }) {
  const { slug } = await params;
  const tool = toolBySlug(slug);
  if (!tool) return { title: "Tool not found" };
  return { title: tool.name };
}

export default async function ToolPage({ params }: { params: Params }) {
  const { slug } = await params;
  const tool = toolBySlug(slug);
  if (!tool) notFound();

  const M = mdxComponents as Record<string, React.ComponentType<React.ComponentProps<"div">>>;
  const H1 = M.h1 as React.ComponentType<React.PropsWithChildren>;
  const H2 = M.h2 as React.ComponentType<React.PropsWithChildren>;
  const P = M.p as React.ComponentType<React.PropsWithChildren>;

  const related = TOOLS.filter(
    (t) => t.id !== tool.id && t.category === tool.category,
  ).slice(0, 4);

  return (
    <div>
      <div className="eyebrow text-graphite">Tools / {tool.category.replace(/_/g, " ")}</div>
      <H1>{tool.name}</H1>
      <P>{tool.blurb}</P>

      <div className="not-prose mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KV label="Tier" value={tool.tier} />
        <KV label="GPU" value={tool.gpu} />
        <KV label="Sec / design" value={`~${tool.estSeconds}s`} />
        <KV label="Category" value={tool.category.replace(/_/g, " ")} />
      </div>

      <H2>When to use it</H2>
      <P>{tool.whenToUse}</P>

      {tool.notes ? (
        <aside className="not-prose my-5 rounded-xl border border-crane/40 bg-crane-glow px-4 py-3">
          <div className="eyebrow mb-1 text-graphite">Note</div>
          <div className="text-[14px] text-ink-soft">{tool.notes}</div>
        </aside>
      ) : null}

      <H2>Run it</H2>
      <pre className="mt-5 overflow-x-auto rounded-xl border border-lattice-strong bg-ink p-4 font-mono text-[13px] leading-6 text-paper">{`papercrane jobs new \\
  --tool ${tool.id} \\
  --target tgt_xxx \\
  --n-designs 50`}</pre>

      <H2>API</H2>
      <pre className="mt-5 overflow-x-auto rounded-xl border border-lattice-strong bg-ink p-4 font-mono text-[13px] leading-6 text-paper">{`POST /v1/jobs
{
  "tool": "${tool.id}",
  "target_id": "tgt_xxx",
  "params": { /* tool-specific */ }
}`}</pre>

      {related.length ? (
        <>
          <H2>Related tools</H2>
          <div className="not-prose mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {related.map((r) => (
              <Link
                key={r.id}
                href={`/tools/${r.id}`}
                className="rounded-xl border border-lattice-strong bg-paper-fold/40 p-4 transition-colors hover:border-ink hover:bg-paper-fold"
              >
                <div className="font-display text-[18px] tracking-tight text-ink">{r.name}</div>
                <p className="mt-1 text-[13px] text-ink-soft">{r.blurb}</p>
              </Link>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-lattice-strong bg-paper-fold/40 px-3 py-2">
      <div className="eyebrow text-graphite">{label}</div>
      <div className="mt-0.5 font-mono text-[13px] text-ink">{value}</div>
    </div>
  );
}
