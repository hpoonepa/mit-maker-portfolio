/**
 * Proxy handler for `/api/trpc/*` on the Next.js dashboard.
 *
 * The Paper Crane tRPC router lives in the Fastify API process (mounted at
 * `${API_BASE_URL}/trpc`, see `packages/trpc/src/routers/index.ts`). The
 * dashboard's `httpBatchLink` already targets that origin directly, but
 * monitoring tools and curl-based smoke checks expect a same-origin
 * `/api/trpc/<procedure>` endpoint on the dashboard itself. This catch-all
 * route forwards those requests to the upstream API verbatim, preserving
 * method, headers, body, and query string so tRPC batching keeps working.
 *
 * We intentionally do NOT import `@trpc/server` here: the dashboard package
 * only carries `@trpc/client`, and the canonical router has already been
 * wired in apps/api with auth/RLS context. Re-instantiating it here would
 * duplicate that wiring and risk drift.
 */
import { NextResponse, type NextRequest } from "next/server";
import { getApiBaseUrl } from "@/lib/trpc/shared";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Hop-by-hop headers MUST NOT be forwarded across a proxy hop.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function filterHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) out.append(key, value);
  });
  return out;
}

async function proxy(req: NextRequest, params: { trpc: string }) {
  const base = getApiBaseUrl().replace(/\/$/, "");
  const search = req.nextUrl.search ?? "";
  const target = `${base}/trpc/${params.trpc}${search}`;

  const init: RequestInit = {
    method: req.method,
    headers: filterHeaders(req.headers),
    redirect: "manual",
    // GET/HEAD must not include a body; everything else streams through.
    body:
      req.method === "GET" || req.method === "HEAD"
        ? undefined
        : await req.arrayBuffer(),
  };

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    return NextResponse.json(
      {
        error: {
          message: `tRPC upstream unreachable at ${target}`,
          code: "BAD_GATEWAY",
          cause: err instanceof Error ? err.message : String(err),
        },
      },
      { status: 502 },
    );
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: filterHeaders(upstream.headers),
  });
}

type RouteContext = { params: Promise<{ trpc: string }> };

export async function GET(req: NextRequest, ctx: RouteContext) {
  return proxy(req, await ctx.params);
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return proxy(req, await ctx.params);
}

export async function OPTIONS(req: NextRequest, ctx: RouteContext) {
  return proxy(req, await ctx.params);
}
