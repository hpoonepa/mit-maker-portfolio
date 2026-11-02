import { Layers, FileText, Hash, Link2 } from "lucide-react";

export type TargetSummaryProps = {
  name: string;
  pdbId: string | null;
  chain: string;
  residueCount: number;
  chainCount: number;
  uploadedAt?: string;
  sizeLabel?: string;
};

/**
 * Compact metadata card for a target: used on the detail page header and
 * below the upload preview. Pure presentational; all data comes from props.
 */
export function TargetSummary(props: TargetSummaryProps) {
  const { name, pdbId, chain, residueCount, chainCount, uploadedAt, sizeLabel } = props;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between gap-6">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Target
          </p>
          <h2 className="mt-1.5 font-display text-[26px] text-ink tracking-[-0.01em]">
            {name}
          </h2>
          {pdbId && (
            <p className="mt-1 font-mono text-[12px] text-graphite">
              PDB {pdbId}
            </p>
          )}
        </div>
        {uploadedAt && (
          <span className="font-mono text-[11px] text-graphite-soft">
            {uploadedAt}
          </span>
        )}
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Stat icon={Link2} label="Chain" value={chain} />
        <Stat icon={Layers} label="Chains" value={String(chainCount)} />
        <Stat icon={Hash} label="Residues" value={residueCount.toLocaleString()} />
        {sizeLabel && <Stat icon={FileText} label="Size" value={sizeLabel} />}
      </dl>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col">
      <dt className="flex items-center gap-1.5 font-sans text-[12px] text-graphite-soft">
        <Icon className="w-3 h-3" />
        {label}
      </dt>
      <dd className="mt-1 font-mono text-[14px] text-ink">{value}</dd>
    </div>
  );
}
