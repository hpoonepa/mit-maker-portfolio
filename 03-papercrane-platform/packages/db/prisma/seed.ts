/**
 * Local dev seed.
 *
 * Creates one development organization (`dev`) on the free tier so that the
 * API, worker, and web apps have something to talk to on `pnpm db:seed`.
 *
 * Also seeds the Tool catalog from `tools/<slug>/manifest.json` so the
 * job-submission tool picker has options.
 *
 * Idempotent — safe to re-run.
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  PrismaClient,
  type Prisma,
  ToolCategory,
  ToolTier,
} from "@prisma/client";

const prisma = new PrismaClient();

// `prisma/seed.ts` → repo root is two levels up.
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = join(__dirname, "..", "..", "..");
const TOOLS_DIR = join(REPO_ROOT, "tools");
const TOOLS_ONLY = process.argv.includes("--tools-only");

const TOOL_SLUGS = [
  "bindcraft",
  "proteinmpnn",
  "rfdiffusion",
  "boltz1",
  "boltz2",
  "chai1",
  "ligandmpnn",
  "solublempnn",
  "esm2",
  "boltzgen",
  "chroma",
  "disco",
  "alphafold3",
  "rfdiffusionaa",
  "esmc",
  "esmfold",
  "germinal",
  "rf3",
  "rfd3",
  "antifold",
  "thermompnn",
  "pdbfixer",
  "esmif1",
  "evoef2",
  "omegafold",
  "immunebuilder",
  "openmm-relax",
  "foldseek",
  "p2rank",
  "freesasa",
  "autodock-vina",
  "plip",
  "mmseqs2",
  "hmmer",
  "mafft",
  "dssp",
  "fpocket",
  "mdanalysis",
  "pdb2pqr",
  "propka",
  "apbs",
  "smina",
  "protparam",
  "parasail",
  "cd-hit",
  "diamond",
  "hhsuite",
  "prody",
  "pdb-tools",
  "prodigy",
  "arpeggio",
  "dockq",
] as const;

// Map manifest category strings → Prisma `ToolCategory` enum.
const CATEGORY_MAP: Record<string, ToolCategory> = {
  backbone_generation: ToolCategory.backbone,
  sequence_design: ToolCategory.sequence,
  structure_prediction: ToolCategory.structure,
  binder_design: ToolCategory.composite,
  embedding_scoring: ToolCategory.ranking,
};

// Map manifest tier strings → Prisma `ToolTier` enum.
// Manifests use "open" / "frontier"; the Prisma enum is free/pro/frontier.
const TIER_MAP: Record<string, ToolTier> = {
  open: ToolTier.free,
  pro: ToolTier.pro,
  frontier: ToolTier.frontier,
};

interface ToolManifest {
  id: string;
  displayName: string;
  version: string;
  adapterVersion: string;
  category: string;
  tier: string;
  license: string;
  image: string;
  imageDigest: string;
  compute: Prisma.InputJsonValue;
  inputSchema: string;
  outputSchema: string;
  defaultParams?: Prisma.InputJsonValue;
  composes?: string[];
}

async function seedTools(): Promise<{ seeded: number; skipped: string[] }> {
  const skipped: string[] = [];
  let seeded = 0;

  for (const slug of TOOL_SLUGS) {
    try {
      const manifestPath = join(TOOLS_DIR, slug, "manifest.json");
      const raw = readFileSync(manifestPath, "utf-8");
      const m = JSON.parse(raw) as ToolManifest;
      const inputSchema = JSON.parse(
        readFileSync(join(TOOLS_DIR, slug, m.inputSchema), "utf-8"),
      ) as Prisma.InputJsonValue;
      const outputSchema = JSON.parse(
        readFileSync(join(TOOLS_DIR, slug, m.outputSchema), "utf-8"),
      ) as Prisma.InputJsonValue;

      const category = CATEGORY_MAP[m.category];
      if (!category) {
        skipped.push(`${slug}: unknown category "${m.category}"`);
        continue;
      }
      const tier = TIER_MAP[m.tier] ?? ToolTier.free;

      const data = {
        displayName: m.displayName,
        version: m.version,
        adapterVersion: m.adapterVersion,
        category,
        tier,
        license: m.license,
        image: m.image,
        imageDigest: m.imageDigest,
        compute: m.compute,
        // Store the schemas themselves so API/UI validation does not depend on
        // the API image containing the worker-only `tools/` source tree.
        inputSchema,
        outputSchema,
        defaultParams: (m.defaultParams ?? {}) as Prisma.InputJsonValue,
        composes: m.composes ?? [],
        active: true,
      };

      await prisma.tool.upsert({
        where: { id: m.id },
        update: data,
        create: { id: m.id, ...data },
      });
      seeded += 1;
    } catch (err) {
      skipped.push(`${slug}: ${(err as Error).message}`);
    }
  }

  return { seeded, skipped };
}

// ─── Sample starter projects ─────────────────────────────────────────────────
//
// Surfaced by `apps/app/components/welcome/SampleProjects.tsx`. Slugs MUST
// match the `SAMPLE_PROJECTS` constant in that file — the "Clone this
// project" mutation looks samples up by slug.
//
// Each sample is owned by the dev org and seeded as a project + a target
// (PDB-only; no artifact bytes — adapters fetch on first run).

interface SampleSpec {
  slug: string;
  name: string;
  description: string;
  pdbId: string;
  targetName: string;
  /** Default tools for the "Clone this project" mutation to pre-select. */
  defaultTools: string[];
  /** Optional hotspots — stored on the Target row as JSON. */
  hotspots?: Prisma.InputJsonValue;
}

const SAMPLE_PROJECTS: SampleSpec[] = [
  {
    slug: "gpcr-binder-6x1a",
    name: "GPCR binder (6X1A)",
    description:
      "De novo binder against CXCR4 (orphan GPCR). BindCraft → Boltz2.",
    pdbId: "6X1A",
    targetName: "CXCR4 · 6X1A",
    defaultTools: ["bindcraft", "boltz2"],
    hotspots: ["A45", "A48", "A52"] as unknown as Prisma.InputJsonValue,
  },
  {
    slug: "antibody-1igt",
    name: "Antibody design (1IGT)",
    description:
      "CDR loop optimization on canonical IgG. RFdiffusion + ProteinMPNN + AlphaFold3.",
    pdbId: "1IGT",
    targetName: "IgG · 1IGT",
    defaultTools: ["rfdiffusion", "proteinmpnn", "alphafold3"],
    hotspots: ["H99", "H100", "H101"] as unknown as Prisma.InputJsonValue,
  },
  {
    slug: "enzyme-1crn",
    name: "Enzyme stabilization (1CRN)",
    description:
      "Stabilize crambin while preserving its hydrophobic core. SolubleMPNN + ESM2.",
    pdbId: "1CRN",
    targetName: "Crambin · 1CRN",
    defaultTools: ["solublempnn", "esm2"],
  },
];

async function seedSampleProjects(orgId: string): Promise<number> {
  let created = 0;
  for (const s of SAMPLE_PROJECTS) {
    const project = await prisma.project.upsert({
      where: { orgId_slug: { orgId, slug: s.slug } },
      update: {
        name: s.name,
        description: s.description,
      },
      create: {
        orgId,
        slug: s.slug,
        name: s.name,
        description: s.description,
      },
    });

    // Idempotent target seeding: keyed by (projectId, name). We don't have a
    // unique constraint on that combo, so we look up first.
    const existing = await prisma.target.findFirst({
      where: { projectId: project.id, name: s.targetName },
      select: { id: true },
    });
    if (!existing) {
      await prisma.target.create({
        data: {
          orgId,
          projectId: project.id,
          name: s.targetName,
          pdbId: s.pdbId,
          // Stable dev placeholder so the row passes schema constraints; the
          // viewer prefers `pdbId` (auto-fetches from RCSB) and falls back to
          // `artifactKey` only when no PDB id is set.
          artifactKey: `dev/seed/${s.pdbId}.pdb`,
          checksum: `sample:${s.pdbId.toLowerCase()}`,
          ...(s.hotspots ? { hotspots: s.hotspots } : {}),
        },
      });
      created += 1;
    }
  }
  return created;
}

async function main() {
  if (TOOLS_ONLY) {
    const { seeded, skipped } = await seedTools();
    // eslint-disable-next-line no-console
    console.log(`seeded tools: ${seeded}/${TOOL_SLUGS.length}`);
    if (skipped.length > 0) {
      // eslint-disable-next-line no-console
      console.warn(`skipped tools:\n  ${skipped.join("\n  ")}`);
    }
    return;
  }

  const org = await prisma.organization.upsert({
    where: { slug: "dev" },
    update: {},
    create: {
      slug: "dev",
      tier: "free",
      seedsQuota: 1_000,
      seedsUsed: 0,
      retentionDays: 30,
      // Explicit so removing the schema default can't silently break the cap.
      gpuSpendCapUsd: 50,
      gpuSpendUsd: 0,
    },
  });

  await prisma.featureFlag.upsert({
    where: { orgId: org.id },
    update: {},
    create: {
      orgId: org.id,
      retentionDays: 30,
      maxConcurrent: 2,
      vpcEnabled: false,
      closedWeightsAllowed: false,
      byocRequired: false,
      // Free tier defaults to "block" — no surprise overage billing.
      // Pro defaults to "overage", Frontier to "overage" (per plan 05 §3).
      onCap: "block",
      notes: "Local dev org — free tier defaults",
    },
  });

  // eslint-disable-next-line no-console
  console.log(`seeded org: ${org.slug} (${org.id})`);

  const { seeded, skipped } = await seedTools();
  // eslint-disable-next-line no-console
  console.log(`seeded tools: ${seeded}/${TOOL_SLUGS.length}`);
  if (skipped.length > 0) {
    // eslint-disable-next-line no-console
    console.warn(`skipped tools:\n  ${skipped.join("\n  ")}`);
  }

  const newSamples = await seedSampleProjects(org.id);
  // eslint-disable-next-line no-console
  console.log(
    `seeded sample projects: ${SAMPLE_PROJECTS.length} (${newSamples} new targets)`,
  );
}

main()
  .catch((err) => {
    // eslint-disable-next-line no-console
    console.error(err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
