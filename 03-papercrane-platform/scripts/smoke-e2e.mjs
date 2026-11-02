#!/usr/bin/env node
// Wave-C E2E smoke — walks the full demo flow end-to-end and prints
// a status/latency table. Exits 0 iff all CRITICAL steps pass.
//
// Usage:   node scripts/smoke-e2e.mjs
// Or:      pnpm smoke
//
// What it does:
//   1. Loads .env.local (NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY).
//   2. Reads demo creds from .agent-logs/20-demo-creds.txt (NEVER hardcoded).
//   3. Hits Supabase Auth REST: POST /auth/v1/token?grant_type=password.
//   4. With the JWT, walks tRPC GETs: projects.list, jobs.list,
//      designs.listByProject (falls back to listByJob), tools.catalog.
//   5. Hits public marketing routes: GET / and GET /benchmark.
//   6. Prints a results table; exits non-zero on any critical failure.
//
// Constraints: Node built-ins only (fs, path, url) + global fetch.
// SAFETY: never logs the password, JWT, or any bearer token.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const ROOT = path.resolve(path.dirname(__filename), "..");
const ENV_PATH = path.join(ROOT, ".env.local");
const CREDS_PATH = path.join(ROOT, ".agent-logs/20-demo-creds.txt");

// ---------- tiny .env loader ----------
function loadDotEnv(p) {
  if (!fs.existsSync(p)) return {};
  const out = {};
  for (const raw of fs.readFileSync(p, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const k = line.slice(0, eq).trim();
    let v = line.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    out[k] = v;
  }
  return out;
}

function loadCreds(p) {
  if (!fs.existsSync(p)) {
    throw new Error(`creds file not found: ${p}`);
  }
  const out = {};
  for (const raw of fs.readFileSync(p, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return out;
}

// ---------- redaction (defence in depth) ----------
function redact(s) {
  return String(s ?? "")
    .replace(/eyJ[A-Za-z0-9_\-\.]+/g, "[REDACTED_JWT]")
    .replace(/Bearer\s+[A-Za-z0-9_\-\.]+/gi, "Bearer [REDACTED]")
    .replace(/sk_[A-Za-z0-9]+/g, "sk_[REDACTED]")
    .replace(/sb-[A-Za-z0-9_\-\.]+/g, "sb-[REDACTED]");
}

// ---------- env + creds ----------
const env = { ...loadDotEnv(ENV_PATH), ...process.env };
const SUPABASE_URL = env.NEXT_PUBLIC_SUPABASE_URL || env.SUPABASE_URL;
const SUPABASE_ANON =
  env.NEXT_PUBLIC_SUPABASE_ANON_KEY || env.SUPABASE_ANON_KEY;
// This is a local smoke test. Production and tunnel URLs in `.env.local`
// must not silently redirect it away from the stack running on this machine.
// Explicit SMOKE_* overrides still support remote staging checks.
const APP_BASE = env.SMOKE_APP_BASE || "http://localhost:3002";
const API_BASE = env.SMOKE_API_BASE || "http://localhost:3001";
const WEB_BASE = env.SMOKE_WEB_BASE || "http://localhost:3000";

if (!SUPABASE_URL || !SUPABASE_ANON) {
  console.error(
    "FATAL: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set in .env.local"
  );
  process.exit(2);
}

const creds = loadCreds(CREDS_PATH);
const EMAIL = creds.email;
const PASSWORD = creds.password;
if (!EMAIL || !PASSWORD) {
  console.error("FATAL: demo creds missing email/password fields");
  process.exit(2);
}

// ---------- result collector ----------
const results = [];
function record(step, status, ms, notes = "", critical = true) {
  results.push({ step, status, ms, notes: redact(notes), critical });
}

async function timed(fn) {
  const t0 = Date.now();
  try {
    const out = await fn();
    return { ms: Date.now() - t0, ...out };
  } catch (e) {
    return { ms: Date.now() - t0, status: 0, ok: false, error: e?.message ?? String(e) };
  }
}

async function getJson(url, headers = {}) {
  const res = await fetch(url, { headers, redirect: "manual" });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* ignore — non-JSON */
  }
  return { status: res.status, ok: res.ok, body };
}

async function getText(url, headers = {}) {
  const res = await fetch(url, { headers, redirect: "manual" });
  return { status: res.status, ok: res.ok };
}

// ---------- 1. auth ----------
async function signIn() {
  const res = await fetch(
    `${SUPABASE_URL}/auth/v1/token?grant_type=password`,
    {
      method: "POST",
      headers: {
        apikey: SUPABASE_ANON,
        "content-type": "application/json",
      },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    }
  );
  const status = res.status;
  let token = null;
  let userId = null;
  try {
    const j = await res.json();
    token = j?.access_token ?? null;
    userId = j?.user?.id ?? null;
  } catch {
    /* ignore */
  }
  return { status, ok: res.ok && !!token, token, userId };
}

// ---------- 2. tRPC GET (query) ----------
function trpcUrl(procedure, input) {
  const base = `${API_BASE}/trpc/${procedure}`;
  if (input === undefined) return base;
  // tRPC v10/v11 GET shape: ?input={"json":<value>}
  return `${base}?input=${encodeURIComponent(JSON.stringify({ json: input }))}`;
}

function trpcOK(body) {
  // Successful tRPC v10/v11 response shape is { result: { data: ... } }
  // batch responses are arrays; a single GET is an object.
  if (!body) return false;
  if (Array.isArray(body)) return body.every((b) => b?.result);
  return Boolean(body.result);
}

function trpcCount(body) {
  const data = body?.result?.data;
  // unwrap superjson { json: ... } if present
  const v = data?.json ?? data;
  if (Array.isArray(v)) return v.length;
  if (Array.isArray(v?.items)) return v.items.length;
  if (Array.isArray(v?.designs)) return v.designs.length;
  if (Array.isArray(v?.tools)) return v.tools.length;
  return null;
}

function firstId(body) {
  const data = body?.result?.data;
  const v = data?.json ?? data;
  const arr = Array.isArray(v)
    ? v
    : Array.isArray(v?.items)
      ? v.items
      : Array.isArray(v?.designs)
        ? v.designs
        : null;
  return arr?.[0]?.id ?? null;
}

// ---------- main ----------
(async () => {
  console.log(`smoke-e2e :: ${new Date().toISOString()}`);
  console.log(`  api=${API_BASE}  app=${APP_BASE}  web=${WEB_BASE}`);
  console.log(`  email=${EMAIL.replace(/(^.).*(@.*$)/, "$1***$2")}`);
  console.log("");

  // 01 — supabase auth
  const auth = await timed(signIn);
  record(
    "auth.signIn",
    auth.ok ? "PASS" : "FAIL",
    auth.ms,
    `status=${auth.status}`,
    true
  );
  if (!auth.ok) {
    return finish(); // can't proceed without a token
  }
  const headers = {
    authorization: `Bearer ${auth.token}`,
    apikey: SUPABASE_ANON,
    "content-type": "application/json",
  };

  // 02 — projects.list (empty-object input required by zod schema)
  const projects = await timed(async () => {
    const r = await getJson(trpcUrl("projects.list", {}), headers);
    return { ...r, ok: r.ok && trpcOK(r.body) };
  });
  const projectId = firstId(projects.body);
  record(
    "trpc.projects.list",
    projects.ok ? "PASS" : "FAIL",
    projects.ms,
    `status=${projects.status} count=${trpcCount(projects.body) ?? "?"}`,
    true
  );

  // 03 — jobs.list (empty-object input required by zod schema)
  const jobs = await timed(async () => {
    const r = await getJson(trpcUrl("jobs.list", {}), headers);
    return { ...r, ok: r.ok && trpcOK(r.body) };
  });
  const jobId = firstId(jobs.body);
  record(
    "trpc.jobs.list",
    jobs.ok ? "PASS" : "FAIL",
    jobs.ms,
    `status=${jobs.status} count=${trpcCount(jobs.body) ?? "?"}`,
    true
  );

  // 04 — designs.listByProject (fallback: listByJob)
  let designs;
  let designsLabel = "designs.listByProject";
  if (projectId) {
    designs = await timed(async () => {
      const r = await getJson(trpcUrl("designs.listByProject", { projectId }), headers);
      return { ...r, ok: r.ok && trpcOK(r.body) };
    });
  } else if (jobId) {
    designsLabel = "designs.listByJob";
    designs = await timed(async () => {
      const r = await getJson(trpcUrl("designs.listByJob", { jobId }), headers);
      return { ...r, ok: r.ok && trpcOK(r.body) };
    });
  } else {
    designs = { ms: 0, ok: false, status: 0 };
    designsLabel = "designs.list*";
  }
  record(
    `trpc.${designsLabel}`,
    designs.ok ? "PASS" : projectId || jobId ? "FAIL" : "SKIP",
    designs.ms,
    `status=${designs.status} count=${trpcCount(designs.body) ?? "?"}`,
    Boolean(projectId || jobId) // critical only if we had something to query
  );

  // 05 — tools.catalog (public — no auth needed but pass header anyway)
  const tools = await timed(async () => {
    const r = await getJson(trpcUrl("tools.catalog"), headers);
    return { ...r, ok: r.ok && trpcOK(r.body) };
  });
  record(
    "trpc.tools.catalog",
    tools.ok ? "PASS" : "FAIL",
    tools.ms,
    `status=${tools.status} count=${trpcCount(tools.body) ?? "?"}`,
    true
  );

  // 06 — marketing /
  const home = await timed(async () => {
    const r = await getText(`${WEB_BASE}/`);
    return { ...r, ok: r.status === 200 };
  });
  record("web.home", home.ok ? "PASS" : "FAIL", home.ms, `status=${home.status}`, true);

  // 07 — marketing /benchmark
  const bench = await timed(async () => {
    const r = await getText(`${WEB_BASE}/benchmark`);
    return { ...r, ok: r.status === 200 };
  });
  record(
    "web.benchmark",
    bench.ok ? "PASS" : "FAIL",
    bench.ms,
    `status=${bench.status}`,
    true
  );

  finish();
})().catch((e) => {
  console.error("FATAL", redact(e?.message ?? String(e)));
  process.exit(1);
});

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s : s + " ".repeat(n - s.length);
}

function finish() {
  // Print table
  console.log("");
  console.log(pad("STEP", 32) + pad("STATUS", 8) + pad("LATENCY", 10) + "NOTES");
  console.log("-".repeat(96));
  for (const r of results) {
    console.log(
      pad(r.step, 32) +
        pad(r.status, 8) +
        pad(`${r.ms}ms`, 10) +
        (r.notes || "")
    );
  }
  const fails = results.filter((r) => r.critical && r.status !== "PASS" && r.status !== "SKIP");
  console.log("-".repeat(96));
  console.log(
    `summary: pass=${results.filter((r) => r.status === "PASS").length} ` +
      `fail=${results.filter((r) => r.status === "FAIL").length} ` +
      `skip=${results.filter((r) => r.status === "SKIP").length} ` +
      `critical_fail=${fails.length}`
  );
  process.exit(fails.length === 0 ? 0 : 1);
}
