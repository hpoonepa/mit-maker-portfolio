type Detail = { label: string; value: string; mono?: boolean; wide?: boolean };
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown) =>
  typeof value === "string" && value.trim() ? value.trim() : null;
const filename = (value: string) =>
  value.includes("/") ? value.split("/").pop() || value : value;

/** Display only submitted values; never substitute current model defaults. */
export function submittedRunDetails(
  params?: Record<string, unknown> | null,
  targetLabel?: string | null,
): Detail[] {
  const raw = record(params);
  const request = raw.request ? record(raw.request) : raw;
  const tool = record(request.toolParams);
  const constraints = record(request.constraints);
  const target = text(request.targetPdb) ?? text(tool.targetPdb) ?? targetLabel;
  const partner = text(request.partnerPdb) ?? text(tool.partnerPdb);
  const chain =
    text(request.targetChain) ??
    text(tool.target_chain) ??
    text(tool.targetChain);
  const rows: Detail[] = [];
  if (target)
    rows.push({ label: "Target", value: filename(target), mono: true });
  if (target)
    rows.push({ label: "Chain", value: chain ?? "Automatic", mono: !!chain });
  if (partner)
    rows.push({
      label: "Partner",
      value: `${filename(partner)}${text(request.partnerChain) ? ` · Chain ${request.partnerChain}` : ""}`,
      mono: true,
    });
  const hotspots = request.hotspots ?? tool.hotspots;
  if (Array.isArray(hotspots) && hotspots.length) {
    const formatted = hotspots
      .map((value) => {
        if (typeof value === "string" || typeof value === "number")
          return String(value);
        const hotspot = record(value);
        return typeof hotspot.chain === "string" &&
          Array.isArray(hotspot.residues)
          ? `${hotspot.chain}: ${hotspot.residues.filter((r) => typeof r === "number").join(", ")}`
          : "";
      })
      .filter(Boolean)
      .join("; ");
    if (formatted)
      rows.push({
        label: "Hotspots",
        value: formatted,
        mono: true,
        wide: true,
      });
  } else if (text(hotspots))
    rows.push({
      label: "Hotspots",
      value: text(hotspots)!,
      mono: true,
      wide: true,
    });
  else if (target && !partner)
    rows.push({ label: "Hotspots", value: "None specified" });
  const contigs = text(tool.contigs);
  const length =
    constraints.lengthRange ?? request.lengthRange ?? tool.binder_length_range;
  if (contigs)
    rows.push({ label: "Contigs", value: contigs, mono: true, wide: true });
  else if (
    Array.isArray(length) &&
    length.length === 2 &&
    length.every((n) => typeof n === "number")
  ) {
    rows.push({
      label: "Binder length",
      value: `${length[0]}–${length[1]} residues`,
    });
  }
  if (Array.isArray(tool.sequences))
    rows.push({
      label: "Input sequences",
      value: String(tool.sequences.length),
    });
  if (!rows.length) rows.push({ label: "Input", value: "Not recorded" });
  return rows;
}
