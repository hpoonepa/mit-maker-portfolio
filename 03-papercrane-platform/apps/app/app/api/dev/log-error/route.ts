/**
 * Dev-only endpoint for the client error logger link.
 *
 * Appends one JSON object per line to `.agent-logs/client-errors.json`
 * (relative to the repo root) so we have a persistent record of every
 * tRPC failure during local development. Production short-circuits
 * with a 404 so this surface never exists in deployed builds.
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const LOG_FILE = path.resolve(
  process.cwd(),
  "..",
  "..",
  ".agent-logs",
  "client-errors.json",
);

export async function POST(req: Request): Promise<Response> {
  if (process.env.NODE_ENV === "production") {
    return new NextResponse(null, { status: 404 });
  }

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "bad json" }, { status: 400 });
  }

  try {
    await fs.mkdir(path.dirname(LOG_FILE), { recursive: true });
    await fs.appendFile(LOG_FILE, `${JSON.stringify(payload)}\n`, "utf8");
  } catch {
    // Don't fail the request: the dev console group already showed the error.
    return NextResponse.json({ ok: false }, { status: 200 });
  }

  return NextResponse.json({ ok: true });
}
