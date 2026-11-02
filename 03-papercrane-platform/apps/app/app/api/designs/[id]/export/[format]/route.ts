/** Authenticated result export. Uses the same org-scoped lookup as the result page. */
import { NextResponse } from "next/server";
import { createServerTrpc } from "@/lib/trpc/server";
import { formatFastaRecord } from "@/lib/export/fasta";
import { formatCsv } from "@/lib/export/csv";
import { betaGateEnabled, normaliseDesignProvenance } from "@papercrane/types";

type Format = "fasta" | "pdb" | "cif" | "json" | "csv";

interface FormatSpec {
  ext: string;
  contentType: string;
}

const FORMATS: Readonly<Record<Format, FormatSpec>> = {
  fasta: { ext: "fasta", contentType: "text/plain; charset=utf-8" },
  pdb: { ext: "pdb", contentType: "text/plain; charset=utf-8" },
  cif: { ext: "cif", contentType: "chemical/x-cif; charset=utf-8" },
  json: { ext: "json", contentType: "application/json; charset=utf-8" },
  csv: { ext: "csv", contentType: "text/csv; charset=utf-8" },
};

const CACHE = "private, no-store";

interface DesignRow {
  id: string;
  seed: number;
  sequence: string | null;
  length: number | null;
  tool: string | null;
  jobId: string;
  provenance: string;
  /** R2 object key for the predicted structure, or null if none was written. */
  artifactKey: string | null;
  metrics: Record<string, number | undefined> | null;
}

/** Pick a stable rank: metrics.rank → metrics.composite_rank → seed. */
function pickRank(row: DesignRow): number | string {
  const m = row.metrics ?? {};
  const r = m.rank ?? m.composite_rank;
  return typeof r === "number" && Number.isFinite(r) ? r : row.seed;
}

/**
 * Explicit, unmistakable PLACEHOLDER returned ONLY when a design has no
 * structure artifact. Every line shouts PLACEHOLDER and contains zero atom
 * records, so it can never be parsed or mistaken for real coordinates.
 */
function placeholderStructure(format: "cif" | "pdb", row: DesignRow): string {
  if (format === "pdb") {
    return [
      `HEADER    PLACEHOLDER - NO STRUCTURE AVAILABLE FOR DESIGN ${row.id}`,
      `TITLE     PLACEHOLDER: this design has no predicted structure (no artifact_key)`,
      `REMARK   1 THIS FILE CONTAINS NO ATOMIC COORDINATES`,
      `REMARK   1 seed=${row.seed} tool=${row.tool ?? "unknown"}`,
      `END`,
      "",
    ].join("\n");
  }
  return [
    `data_PLACEHOLDER_${row.id.slice(0, 8)}`,
    `# PLACEHOLDER: this design has no predicted structure (no artifact_key)`,
    `# THIS FILE CONTAINS NO ATOMIC COORDINATES`,
    `_entry.id PLACEHOLDER_${row.id.slice(0, 8)}`,
    "",
  ].join("\n");
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string; format: string }> },
) {
  const { id, format: rawFormat } = await ctx.params;
  const format = rawFormat as Format;

  if (!Object.prototype.hasOwnProperty.call(FORMATS, format)) {
    // 404 (not 400): mirrors Next.js dynamic-segment semantics for unknown
    // path values. The body is JSON so XHR clients still get something useful.
    return NextResponse.json(
      { error: `unknown format: ${rawFormat}` },
      { status: 404 },
    );
  }

  const client = await createServerTrpc();
  if (betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE)) {
    try {
      const admission = await client.beta.accessStatus.query();
      if (!admission.granted) return NextResponse.json({ error: "A valid beta invite is required." }, { status: 403 });
    } catch {
      return NextResponse.json({ error: "Beta access could not be verified. Please sign in and retry." }, { status: 503 });
    }
  }

  let data: Awaited<ReturnType<typeof client.designs.get.query>>;
  try {
    data = await client.designs.get.query({ id });
  } catch (error) {
    const code = (error as { data?: { code?: string } })?.data?.code;
    const status = code === "NOT_FOUND" ? 404 : code === "UNAUTHORIZED" ? 401 : code === "FORBIDDEN" ? 403 : 503;
    return NextResponse.json({ error: status === 404 ? "Result not found." : status === 401 ? "Please sign in to download this result." : status === 403 ? "You do not have access to this result." : "Result temporarily unavailable. Please retry." }, { status });
  }
  if (!data) return NextResponse.json({ error: "Result not found." }, { status: 404 });

  const m = (data.metrics ?? {}) as Record<string, unknown>;
  const row: DesignRow = {
    id: data.id as string,
    seed: data.seed as number,
    sequence: typeof m.sequence === "string" ? (m.sequence as string) : null,
    length:
      typeof m.length === "number"
        ? (m.length as number)
        : typeof m.sequence === "string"
          ? (m.sequence as string).length
          : null,
    tool: data.tool ?? (typeof m.tool === "string" ? m.tool : null),
    jobId: data.jobId as string,
    provenance: normaliseDesignProvenance(data.provenance),
    artifactKey:
      typeof data.artifactKey === "string" && data.artifactKey.length > 0
        ? (data.artifactKey as string)
        : null,
    metrics: m as Record<string, number | undefined>,
  };
  const metrics = row.metrics ?? {};
  const rank = pickRank(row);
  const idPrefix = row.id.slice(0, 8);
  const spec = FORMATS[format];
  const filename = `design-${rank}-${idPrefix}.${spec.ext}`;

  const headers: Record<string, string> = {
    "content-type": spec.contentType,
    "content-disposition": `attachment; filename="${filename}"`,
    "cache-control": CACHE,
  };

  if (format === "fasta") {
    if (!row.sequence) {
      return NextResponse.json({ error: "No sequence is recorded for this design." }, { status: 409 });
    }
    const body = formatFastaRecord({
      id: row.id,
      seed: row.seed,
      sequence: row.sequence ?? "",
      provenance: row.provenance,
      metrics,
    });
    return new Response(body, { headers });
  }

  if (format === "csv") {
    const body = formatCsv([
      {
        id: row.id,
        seed: row.seed,
        sequence: row.sequence,
        length: row.length,
        tool: row.tool,
        provenance: row.provenance,
        metrics,
      },
    ]);
    return new Response(body, { headers });
  }

  if (format === "cif" || format === "pdb") {
    // Resolve the REAL structure bytes from R2. We reuse the trpc `designs.get`
    // presign path, then stream through this authenticated same-origin route.
    if (row.artifactKey) {
      try {
        const design = data;
        if (design?.structureUrl) {
          const upstream = await fetch(design.structureUrl, {
            cache: "no-store",
          });
          if (!upstream.ok || !upstream.body) {
            throw new Error(`R2 returned HTTP ${upstream.status}`);
          }
          const content = await upstream.text();
          const actualFormat = /^data_\S+/m.test(content)
            ? "cif"
            : /^(?:ATOM  |HETATM|HEADER|MODEL )/m.test(content)
              ? "pdb"
              : null;
          if (actualFormat !== format) {
            return NextResponse.json({
              error: actualFormat
                ? `This artifact is ${actualFormat.toUpperCase()}. Download that format; conversion is not available.`
                : "The stored artifact is not a recognized PDB or mmCIF file.",
              availableFormat: actualFormat,
            }, { status: 409, headers: { "cache-control": "no-store" } });
          }
          return new Response(content, { headers });
        }
        throw new Error("design presign returned no structure URL");
      } catch (err) {
        console.error("[api/designs/export] structure stream failed", err);
        return NextResponse.json(
          { error: "structure temporarily unavailable" },
          {
            status: 502,
            headers: { "cache-control": "no-store" },
          },
        );
      }
    }

    // No artifact: return an unmistakable placeholder with HTTP 409 so it can
    // NEVER masquerade as real coordinates.
    const placeholderName = `design-${rank}-${idPrefix}_PLACEHOLDER.${spec.ext}`;
    return new Response(placeholderStructure(format, row), {
      status: 409,
      headers: {
        ...headers,
        "content-disposition": `attachment; filename="${placeholderName}"`,
        "x-papercrane-placeholder": "1",
      },
    });
  }

  // format === "json"
  return new Response(JSON.stringify(row, null, 2), { headers });
}
