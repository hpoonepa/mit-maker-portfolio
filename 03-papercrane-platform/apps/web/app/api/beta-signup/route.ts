import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const runtime = "nodejs";

const SIGNUP_LOG = "/tmp/papercrane-beta-signups.jsonl";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function err(message: string, status = 400) {
  return NextResponse.json({ error: message }, { status });
}

function clean(v: unknown, max = 2000): string {
  if (typeof v !== "string") return "";
  return v.trim().slice(0, max);
}

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return err("INVALID JSON");
  }

  const email = clean(body.email, 320).toLowerCase();
  const name = clean(body.name, 200);
  const org = clean(body.org, 200);
  const useCase = clean(body.useCase, 2000);
  const target = clean(body.target, 200);

  if (!email) return err("EMAIL REQUIRED");
  if (!EMAIL_RE.test(email)) return err("INVALID EMAIL");

  const record = {
    ts: new Date().toISOString(),
    email,
    name,
    org,
    useCase,
    target,
    ip: req.headers.get("x-forwarded-for") ?? null,
    ua: req.headers.get("user-agent") ?? null,
  };

  try {
    await fs.mkdir(path.dirname(SIGNUP_LOG), { recursive: true });
    await fs.appendFile(SIGNUP_LOG, JSON.stringify(record) + "\n", "utf8");
  } catch (e) {
    // Logging failure must not block beta signup; surface generic 500 only
    // if write truly fails. Most environments allow /tmp writes.
    console.error("[beta-signup] failed to append log", e);
    return NextResponse.json({ ok: true, persisted: false });
  }

  return NextResponse.json({ ok: true, persisted: true });
}

export async function GET() {
  return err("METHOD NOT ALLOWED", 405);
}
