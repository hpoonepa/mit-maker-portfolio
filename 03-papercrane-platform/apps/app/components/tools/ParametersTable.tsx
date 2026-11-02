/**
 * ParametersTable: reference table for tool detail page.
 *
 * The platform does not (yet) ship per-tool parameter manifests on the wire,
 * so we surface the catalog's first-class compute + tier fields as the
 * "parameters reference" for now. This is honest: every value here comes
 * straight from the proc, nothing is fabricated.
 *
 * Once a richer per-tool param schema lands on `tools.get`, swap the rows
 * for that data without touching the detail page.
 */
type Row = { label: string; value: string };

export function ParametersTable({ rows }: { rows: Row[] }) {
  return (
    <section className="space-y-6">
      <header className="flex items-baseline justify-between pb-3">
        <h2 className="font-display text-[1.5rem] tracking-[-0.02em] text-ink">
          Reference
        </h2>
        <span className="font-sans text-[12px] text-graphite-soft">
          Catalog values
        </span>
      </header>
      <dl className="grid grid-cols-1 md:grid-cols-2">
        {rows.map((r) => (
          <div
            key={r.label}
            className="flex items-baseline justify-between gap-4 py-3"
          >
            <dt className="font-sans text-[12px] text-graphite-soft">
              {r.label}
            </dt>
            <dd className="font-mono text-[12px] tracking-tight text-ink">
              {r.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
