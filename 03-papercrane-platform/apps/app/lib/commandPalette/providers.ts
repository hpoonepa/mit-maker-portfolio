/**
 * Live-result providers for the command palette.
 *
 * These are async functions: one per data domain: that return a promise of
 * `Command[]` filtered by the user's query. The palette calls them with
 * debouncing; each provider is expected to short-circuit empty queries
 * (return []) so the idle state stays lean.
 *
 * tRPC wiring
 * -----------
 * The real implementation will call into `@papercrane/trpc`. Because that
 * module is not fully stable yet: and because tRPC hooks cannot be invoked
 * from plain module functions (only from React components): we provide a
 * `buildProviders` factory that accepts a client and returns concrete
 * providers. The default export (`defaultProviders`) is a no-dep stub that
 * hits local catalogs for tools/docs and returns [] for everything else,
 * with a TODO comment flagging the wiring work.
 */

import type { Command } from "./registry";
import { fuzzyRank } from "./fuzzy";

export interface SearchProviders {
  projects: (q: string) => Promise<Command[]>;
  jobs: (q: string) => Promise<Command[]>;
  targets: (q: string) => Promise<Command[]>;
  tools: (q: string) => Promise<Command[]>;
  docs: (q: string) => Promise<Command[]>;
}

/**
 * Minimal tRPC contract. Any client with `.query(path, input)` satisfies it.
 * Typed loosely on purpose: the palette should survive schema drift.
 */
export interface TrpcLike {
  query: (path: string, input: unknown) => Promise<unknown>;
}

/* ------------------------------------------------------------------ */
/* Tools catalog: static, 12 entries matching the Paper Crane lineup */
/* ------------------------------------------------------------------ */

interface CatalogEntry {
  slug: string;
  name: string;
  description: string;
  keywords: string[];
}

const TOOLS_CATALOG: CatalogEntry[] = [
  { slug: "rfdiffusion", name: "RFdiffusion", description: "Backbone diffusion generator", keywords: ["backbone", "diffusion", "design"] },
  { slug: "boltzgen", name: "BoltzGen", description: "All-atom binder design", keywords: ["all-atom", "design", "ligand"] },
  { slug: "bindcraft", name: "BindCraft", description: "End-to-end binder hallucination", keywords: ["hallucination", "design"] },
  { slug: "proteinmpnn", name: "ProteinMPNN", description: "Sequence inverse folding", keywords: ["sequence", "mpnn", "inverse"] },
  { slug: "ligandmpnn", name: "LigandMPNN", description: "Ligand-aware sequence design", keywords: ["sequence", "mpnn", "ligand"] },
  { slug: "solublempnn", name: "SolubleMPNN", description: "Solubility-optimized design", keywords: ["sequence", "mpnn", "expression"] },
  { slug: "alphafold", name: "AlphaFold2", description: "Structure prediction (Multimer)", keywords: ["structure", "fold", "af2"] },
  { slug: "boltz", name: "Boltz-2", description: "Open biomolecular structure predictor", keywords: ["structure", "fold"] },
  { slug: "chai", name: "Chai-1", description: "Foundation structure model", keywords: ["structure", "fold"] },
  { slug: "esm", name: "ESM2", description: "Protein language model scoring", keywords: ["embed", "plm", "score"] },
  { slug: "foldseek", name: "Foldseek", description: "Structural homology search", keywords: ["search", "homolog", "pdb"] },
  { slug: "ipsae", name: "ipSAE", description: "Binder design ranker", keywords: ["rank", "metric", "score"] },
];

/** Known top-level docs pages. TODO: wire real docs search against content/docs. */
const DOCS_CATALOG: CatalogEntry[] = [
  { slug: "getting-started", name: "Getting Started", description: "/docs/getting-started", keywords: ["intro", "quickstart"] },
  { slug: "quickstart-cli", name: "Quickstart (CLI)", description: "/docs/quickstart-cli", keywords: ["cli", "terminal"] },
  { slug: "api-reference", name: "API Reference", description: "/docs/api", keywords: ["api", "rest", "rpc"] },
  { slug: "sdk-python", name: "Python SDK", description: "/docs/sdk/python", keywords: ["python", "sdk"] },
  { slug: "sdk-typescript", name: "TypeScript SDK", description: "/docs/sdk/typescript", keywords: ["ts", "sdk"] },
  { slug: "webhooks", name: "Webhooks Guide", description: "/docs/webhooks", keywords: ["webhook", "events"] },
  { slug: "billing", name: "Billing & Usage", description: "/docs/billing", keywords: ["invoice", "gpu", "plan"] },
  { slug: "changelog", name: "Changelog", description: "/docs/changelog", keywords: ["updates", "release"] },
];

/* ------------------------------------------------------------------ */
/* Shaping helpers                                                    */
/* ------------------------------------------------------------------ */

function toolToCommand(entry: CatalogEntry): Command {
  return {
    id: `tool.${entry.slug}`,
    title: entry.name,
    subtitle: entry.description,
    group: "Tools",
    icon: "wrench",
    keywords: entry.keywords,
    action: ({ router }) => router?.push(`/tools/${entry.slug}`),
  };
}

function docToCommand(entry: CatalogEntry): Command {
  return {
    id: `doc.${entry.slug}`,
    title: entry.name,
    subtitle: entry.description,
    group: "Docs",
    icon: "book-open",
    keywords: entry.keywords,
    action: ({ router }) => router?.push(`/docs/${entry.slug}`),
  };
}

function projectToCommand(row: { id: string; name: string }): Command {
  return {
    id: `project.${row.id}`,
    title: row.name,
    subtitle: `Open project ${row.id}`,
    group: "Projects",
    icon: "folder",
    keywords: ["project", "workspace"],
    action: ({ router }) => router?.push(`/projects/${row.id}`),
  };
}

function jobToCommand(row: { id: string; name: string; status?: string }): Command {
  return {
    id: `job.${row.id}`,
    title: row.name,
    subtitle: row.status ? `Job · ${row.status}` : `Open job ${row.id}`,
    group: "Jobs",
    icon: "play-circle",
    keywords: ["job", "run"],
    action: ({ router }) => router?.push(`/jobs/${row.id}`),
  };
}

function targetToCommand(row: { id: string; name: string }): Command {
  return {
    id: `target.${row.id}`,
    title: row.name,
    subtitle: `Open target ${row.id}`,
    group: "Targets",
    icon: "target",
    keywords: ["target", "pdb"],
    action: ({ router }) => router?.push(`/targets/${row.id}`),
  };
}

/* ------------------------------------------------------------------ */
/* Factory over a tRPC-like client                                    */
/* ------------------------------------------------------------------ */

export function buildProviders(trpc: TrpcLike): SearchProviders {
  const searchViaTrpc = async <T,>(
    path: string,
    q: string,
    fallback: T[] = [],
  ): Promise<T[]> => {
    if (!q.trim()) return [];
    try {
      const res = await trpc.query(path, { q });
      return Array.isArray(res) ? (res as T[]) : fallback;
    } catch {
      // TODO: surface errors through a toast channel; silent fail keeps the
      // palette usable even when a single provider is flaky.
      return fallback;
    }
  };

  return {
    projects: async (q) => {
      const rows = await searchViaTrpc<{ id: string; name: string }>(
        "projects.search",
        q,
      );
      return rows.map(projectToCommand);
    },
    jobs: async (q) => {
      // TODO: confirm `jobs.search` procedure exists on the tRPC router.
      // If not, fall back to client-side filter over `jobs.list`.
      const rows = await searchViaTrpc<{ id: string; name: string; status?: string }>(
        "jobs.search",
        q,
      );
      return rows.map(jobToCommand);
    },
    targets: async (q) => {
      const rows = await searchViaTrpc<{ id: string; name: string }>(
        "targets.search",
        q,
      );
      return rows.map(targetToCommand);
    },
    tools: async (q) => filterCatalog(TOOLS_CATALOG, q).map(toolToCommand),
    docs: async (q) => filterCatalog(DOCS_CATALOG, q).map(docToCommand),
  };
}

/* ------------------------------------------------------------------ */
/* Dep-free default: tools/docs only, stubs for remote providers     */
/* ------------------------------------------------------------------ */

export const defaultProviders: SearchProviders = {
  // TODO: wire via buildProviders(trpcClient) once the client is in scope.
  projects: async () => [],
  jobs: async () => [],
  targets: async () => [],
  tools: async (q) => filterCatalog(TOOLS_CATALOG, q).map(toolToCommand),
  docs: async (q) => filterCatalog(DOCS_CATALOG, q).map(docToCommand),
};

function filterCatalog(catalog: CatalogEntry[], q: string): CatalogEntry[] {
  if (!q.trim()) return [];
  const items = catalog.map((entry) => ({
    id: entry.slug,
    title: entry.name,
    keywords: entry.keywords,
    _src: entry,
  }));
  return fuzzyRank(items, q).map((item) => item._src);
}
