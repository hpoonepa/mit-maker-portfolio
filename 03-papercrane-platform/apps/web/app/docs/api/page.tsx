import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "API reference";
const DESCRIPTION =
  "Paper Crane REST API — authentication, jobs, designs, and projects. Source of truth: tRPC routers in packages/trpc.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/docs/api",
  ogTitle: "API reference",
  ogDesc: "Endpoints. Schemas. Curl.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Docs", path: "/docs" },
  { name: "API", path: "/docs/api" },
];

// ---------- Endpoint catalog ----------
// Source of truth: packages/trpc/src/routers/{keys,jobs,designs,projects}.ts
type Endpoint = {
  id: string;
  verb: "GET" | "POST" | "PATCH" | "DELETE";
  path: string;
  proc: string;
  desc: string;
  request?: string;
  response: string;
  curl: string;
};

const BASE = "https://api.papercrane.bio/v1";

const ENDPOINTS: Endpoint[] = [
  {
    id: "keys-create",
    verb: "POST",
    path: "/v1/keys",
    proc: "keys.create",
    desc:
      "Mint an API key. Plaintext is returned once and never stored — copy it immediately. Subsequent calls only expose the prefix.",
    request: `{
  "name": "ci-prod-key",
  "scopes": ["jobs:write", "designs:read"],
  "expiresAt": "2027-01-01T00:00:00Z"
}`,
    response: `{
  "id": "key_01HZ...",
  "prefix": "pk_live_8f2a",
  "plaintext": "pk_live_8f2a...d09e",
  "createdAt": "2026-04-29T18:22:11Z"
}`,
    curl: `curl -X POST ${BASE}/keys \\
  -H "Authorization: Bearer $PAPERCRANE_SESSION" \\
  -H "Content-Type: application/json" \\
  -d '{"name":"ci-prod-key","scopes":["jobs:write"]}'`,
  },
  {
    id: "jobs-submit",
    verb: "POST",
    path: "/v1/jobs",
    proc: "jobs.submit",
    desc:
      "Submit a design job with one runnable tool and a DesignRequest. The worker emits one design per unique seed, so numDesigns must equal seeds.length. Returns immediately with a queued job id.",
    request: `{
  "toolId": "bindcraft",
  "request": {
    "targetPdb": "2LGV",
    "targetChain": "A",
    "hotspots": [{ "chain": "A", "residues": [45, 48, 52] }],
    "numDesigns": 5,
    "seeds": [1, 2, 3, 4, 5]
  },
  "webhookUrl": "https://example.com/hooks/papercrane",
  "idempotencyKey": "campaign-2026-04-29-001"
}`,
    response: `{
  "id": "job_01HZ...",
  "toolId": "bindcraft",
  "status": "queued",
  "submittedAt": "2026-04-29T18:23:04Z",
  "numDesigns": 5,
  "completedDesigns": 0,
  "etaSeconds": 230
}`,
    curl: `curl -X POST ${BASE}/jobs \\
  -H "Authorization: Bearer $PAPERCRANE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d @job.json`,
  },
  {
    id: "jobs-get",
    verb: "GET",
    path: "/v1/jobs/{id}",
    proc: "jobs.get",
    desc:
      "Poll job state. Status transitions: queued → preparing → running → (succeeded | partial | failed | cancelled).",
    response: `{
  "id": "job_01HZ...",
  "toolId": "bindcraft",
  "status": "running",
  "submittedAt": "2026-04-29T18:23:04Z",
  "startedAt":   "2026-04-29T18:23:41Z",
  "numDesigns": 100,
  "completedDesigns": 37
}`,
    curl: `curl ${BASE}/jobs/job_01HZ... \\
  -H "Authorization: Bearer $PAPERCRANE_API_KEY"`,
  },
  {
    id: "designs-get",
    verb: "GET",
    path: "/v1/designs/{id}",
    proc: "designs.get",
    desc:
      "Fetch a single design. Response includes metrics and a presigned URL pointing to the structure artifact (CIF) in object storage.",
    response: `{
  "id": "des_01HZ...",
  "jobId": "job_01HZ...",
  "seed": 17,
  "rank": 3,
  "metrics": {
    "ipsae": 0.81,
    "iptm":  0.74,
    "plddt": 88.2
  },
  "structureUrl": "https://artifacts.papercrane.bio/...sig=...",
  "structureFormat": "cif"
}`,
    curl: `curl ${BASE}/designs/des_01HZ... \\
  -H "Authorization: Bearer $PAPERCRANE_API_KEY"`,
  },
  {
    id: "designs-list",
    verb: "GET",
    path: "/v1/jobs/{jobId}/designs",
    proc: "designs.listByJob",
    desc:
      "List every design produced by a job, ordered by rank. Use this to drive ranking tables and bulk-export pipelines client-side (download structures via each design's presigned URL).",
    response: `{
  "designs": [
    { "id": "des_01HZ...a", "seed": 1,  "rank": 1, "metrics": { "ipsae": 0.83 } },
    { "id": "des_01HZ...b", "seed": 17, "rank": 2, "metrics": { "ipsae": 0.81 } }
  ],
  "nextCursor": null
}`,
    curl: `curl ${BASE}/jobs/job_01HZ.../designs \\
  -H "Authorization: Bearer $PAPERCRANE_API_KEY"`,
  },
  {
    id: "projects-create",
    verb: "POST",
    path: "/v1/projects",
    proc: "projects.create",
    desc:
      "Create a project. Projects are the org-scoped container for jobs, targets, and designs.",
    request: `{
  "name": "RBX1 binder campaign",
  "description": "BindCraft sweep against 2LGV chain A"
}`,
    response: `{
  "id": "prj_01HZ...",
  "name": "RBX1 binder campaign",
  "createdAt": "2026-04-29T18:24:55Z"
}`,
    curl: `curl -X POST ${BASE}/projects \\
  -H "Authorization: Bearer $PAPERCRANE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"name":"RBX1 binder campaign"}'`,
  },
];

const MONO = "font-mono text-[13px] leading-relaxed";

function MethodPill({ verb }: { verb: Endpoint["verb"] }) {
  return (
    <span
      className={`inline-block ${MONO} px-2 py-[2px] border border-stone-300 text-stone-700 rounded-sm tracking-tight`}
    >
      {verb}
    </span>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre
      className={`${MONO} bg-stone-50 border border-stone-200 rounded-sm px-4 py-3 overflow-x-auto text-stone-800 whitespace-pre`}
    >
      {children}
    </pre>
  );
}

export default function ApiReferencePage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main className="min-h-screen bg-white text-stone-900">
        <section className="mx-auto max-w-3xl px-6 pt-28 pb-20">
          <Reveal>
            <nav className={`${MONO} text-stone-500 mb-8`} aria-label="Breadcrumb">
              <Link href="/docs" className="hover:text-stone-900">
                docs
              </Link>
              <span className="mx-2">/</span>
              <span className="text-stone-900">api</span>
            </nav>

            <h1 className="text-4xl md:text-5xl font-serif tracking-tight mb-6">
              API reference
            </h1>
            <p className="text-stone-600 max-w-2xl text-lg leading-relaxed">
              Paper Crane exposes a thin REST surface over its tRPC core. Every
              endpoint below is generated from a procedure in{" "}
              <code className={MONO}>packages/trpc/src/routers</code> — the same
              source of truth used by the dashboard.
            </p>
          </Reveal>

          {/* ---------- Auth ---------- */}
          <Reveal>
            <div className="mt-16">
              <h2 id="auth" className="text-2xl font-serif tracking-tight mb-3">
                Authentication
              </h2>
              <p className="text-stone-600 mb-5 leading-relaxed">
                All requests require a bearer token. Mint one from the dashboard
                or via the <code className={MONO}>keys.create</code> procedure.
                The plaintext key is shown <em>once</em> — store it in your
                secret manager, then reference it via the{" "}
                <code className={MONO}>Authorization</code> header.
              </p>
              <CodeBlock>{`Authorization: Bearer pk_live_8f2a...d09e
Content-Type:  application/json`}</CodeBlock>
              <p className={`${MONO} text-stone-500 mt-3 text-xs`}>
                Keys can be rotated (24h grace) or revoked immediately. See{" "}
                <code>keys.rotate</code> and <code>keys.revoke</code>.
              </p>
            </div>
          </Reveal>

          {/* ---------- Endpoints ---------- */}
          <div className="mt-16 space-y-0">
            {ENDPOINTS.map((ep, i) => (
              <Reveal key={ep.id}>
                <article id={ep.id} className="py-10">
                  {i > 0 && (
                    <hr
                      aria-hidden
                      className="border-0 border-t border-stone-200 mb-10 -mt-10"
                    />
                  )}

                  <div className="flex items-baseline gap-3 flex-wrap mb-2">
                    <MethodPill verb={ep.verb} />
                    <code className={`${MONO} text-stone-900`}>{ep.path}</code>
                    <span className={`${MONO} text-stone-400 text-xs`}>
                      {ep.proc}
                    </span>
                  </div>

                  <p className="text-stone-600 leading-relaxed mb-6 max-w-2xl">
                    {ep.desc}
                  </p>

                  {ep.request && (
                    <div className="mb-5">
                      <div className={`${MONO} text-xs text-stone-500 mb-2`}>
                        request
                      </div>
                      <CodeBlock>{ep.request}</CodeBlock>
                    </div>
                  )}

                  <div className="mb-5">
                    <div className={`${MONO} text-xs text-stone-500 mb-2`}>
                      response (200)
                    </div>
                    <CodeBlock>{ep.response}</CodeBlock>
                  </div>

                  <div>
                    <div className={`${MONO} text-xs text-stone-500 mb-2`}>
                      curl
                    </div>
                    <CodeBlock>{ep.curl}</CodeBlock>
                  </div>
                </article>
              </Reveal>
            ))}
          </div>

          {/* ---------- Footer note ---------- */}
          <Reveal>
            <hr aria-hidden className="border-0 border-t border-stone-200 mt-6" />
            <p className={`${MONO} text-stone-500 text-xs mt-8 leading-relaxed`}>
              Errors follow tRPC conventions: HTTP 400 (BAD_REQUEST), 401
              (UNAUTHORIZED), 403 (FORBIDDEN), 404 (NOT_FOUND), 429
              (TOO_MANY_REQUESTS), 500 (INTERNAL_SERVER_ERROR). Bodies are JSON
              with <code>{`{ error: { code, message } }`}</code>.
            </p>
            <p className="text-stone-500 text-sm mt-6">
              Looking for the CLI?{" "}
              <Link href="/docs/cli" className="underline hover:text-stone-900">
                /docs/cli
              </Link>
              . Or get oriented at{" "}
              <Link
                href="/docs/getting-started"
                className="underline hover:text-stone-900"
              >
                /docs/getting-started
              </Link>
              .
            </p>
          </Reveal>
        </section>
        <Footer />
      </main>
    </>
  );
}
