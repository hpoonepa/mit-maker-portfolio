/**
 * GET /api/pdb/[id]?format=cif|pdb|auto: server-side proxy to RCSB.
 *
 * Fixes the prior client-side fetch that failed on browsers blocking
 * cross-origin HEADs against files.rcsb.org. By proxying through Node we
 * also bypass any CORS preflight and can centralise caching.
 */
import { NextResponse } from "next/server";
import { pdbIdSchema, type PdbFormat } from "@/lib/pdb/fetch";

// Node runtime: streaming large CIFs through the edge runtime can truncate
// for entries >4 MB, and we want predictable timeouts.
export const runtime = "nodejs";

// `/download/` returns the raw file body; `/view/` redirects to a viewer
// page in some cases. We always want the file.
const RCSB_DOWNLOAD_BASE = "https://files.rcsb.org/download";

type RequestedFormat = PdbFormat | "auto";

function parseFormat(raw: string | null): RequestedFormat {
  if (raw === "pdb" || raw === "cif") return raw;
  return "auto";
}

function contentTypeFor(format: PdbFormat): string {
  return format === "cif" ? "chemical/x-cif" : "chemical/x-pdb";
}

async function fetchOne(
  validId: string,
  format: PdbFormat,
  signal: AbortSignal,
): Promise<Response> {
  const url = `${RCSB_DOWNLOAD_BASE}/${validId}.${format}`;
  return fetch(url, { signal, redirect: "follow" });
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id: rawId } = await params;

  const parsed = pdbIdSchema.safeParse(rawId);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_pdb_id", message: parsed.error.errors[0]?.message },
      { status: 400 },
    );
  }
  const validId = parsed.data;

  const url = new URL(req.url);
  const requested = parseFormat(url.searchParams.get("format"));
  const tryOrder: PdbFormat[] =
    requested === "auto" ? ["cif", "pdb"] : [requested];

  let lastUpstreamStatus = 0;

  for (const fmt of tryOrder) {
    let upstream: Response;
    try {
      upstream = await fetchOne(validId, fmt, req.signal);
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        return new Response(null, { status: 499 });
      }
      lastUpstreamStatus = 502;
      continue;
    }

    if (upstream.ok && upstream.body) {
      return new Response(upstream.body, {
        status: 200,
        headers: {
          "content-type": contentTypeFor(fmt),
          "cache-control":
            "public, s-maxage=86400, stale-while-revalidate=604800",
          "access-control-allow-origin": "*",
          "x-pdb-format": fmt,
          "x-pdb-id": validId,
        },
      });
    }

    if (upstream.status === 404) {
      // Try next format if we're in auto mode; otherwise fall through to 404.
      lastUpstreamStatus = 404;
      continue;
    }

    if (upstream.status >= 500) {
      lastUpstreamStatus = upstream.status;
      continue;
    }

    // Other 4xx: treat as not_found (RCSB only really returns 404 here).
    lastUpstreamStatus = upstream.status;
    break;
  }

  if (lastUpstreamStatus === 404) {
    return NextResponse.json(
      { error: "not_found", pdbId: validId },
      {
        status: 404,
        headers: { "cache-control": "public, s-maxage=600" },
      },
    );
  }

  return NextResponse.json(
    { error: "upstream_failed", pdbId: validId, upstreamStatus: lastUpstreamStatus },
    { status: 502 },
  );
}
