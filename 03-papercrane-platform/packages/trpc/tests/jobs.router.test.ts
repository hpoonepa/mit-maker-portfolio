import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { appRouter } from "../src/routers/index.js";
import { createInnerContext } from "../src/context.js";
import type { AuthContext } from "../src/context.js";

/**
 * Jobs router — POST-style submit.
 *
 * Contract:
 *   - rejects unauthenticated callers
 *   - accepts authenticated callers whose tier has the tool in its allowlist
 *   - rejects authenticated callers whose tier does NOT have the tool
 *   - inserts a job row inside withRlsUser and enqueues onto the tier queue
 */

const USER_ID = "00000000-0000-4000-8000-000000000001";
const ORG_ID = "00000000-0000-4000-8000-00000000aaaa";

function makeAuth(tier: "free" | "pro" | "frontier"): AuthContext {
  return {
    kind: "user",
    userId: USER_ID,
    orgId: ORG_ID,
    orgSlug: "acme",
    tier,
    scopes: ["*"],
  };
}

const REQUEST = {
  toolId: "boltz2",
  request: {
    targetPdb: "1ABC",
    seeds: [0, 1, 2],
    numDesigns: 3,
  },
};

const AF3_REQUEST = {
  ...REQUEST,
  toolId: "alphafold3",
};

const CHAI1_REQUEST = {
  ...REQUEST,
  toolId: "chai1",
};

const EXPERIMENTAL_REQUEST = {
  ...REQUEST,
  toolId: "rfdiffusion",
};

/** Submission whose seed count (100) blows past the default per-job cap (25). */
const OVER_CAP_REQUEST = {
  toolId: "boltz2",
  request: {
    targetPdb: "1ABC",
    seeds: Array.from({ length: 100 }, (_v, i) => i),
    numDesigns: 100,
  },
};

beforeEach(() => {
  process.env.WORKER_DEV_MODE = "false";
  delete process.env.MODAL_TOKEN_ID;
  delete process.env.MODAL_TOKEN_SECRET;
});

afterEach(() => {
  delete process.env.WORKER_DEV_MODE;
});

function createdJobRow() {
  return {
    id: "00000000-0000-4000-8000-0000000000ff",
    orgId: ORG_ID,
    toolId: REQUEST.toolId,
    status: "queued",
    submittedAt: new Date("2026-04-23T12:00:00Z"),
    numDesigns: 3,
    completedDesigns: 0,
  };
}

function buildHarness({
  auth,
  enqueue = vi.fn().mockResolvedValue(undefined),
  seedsQuota = 1000,
  seedsUsed = 0,
  activeJobs = [],
  maxConcurrent = 2,
  gpuSpendCapUsd = 50,
  gpuSpendUsd = 0,
  toolVersion = "1.2.3",
  toolAdapterVersion = "a3",
  toolImageDigest = "sha256:abc",
  toolCompute = null,
  toolInputSchema,
  toolDefaultParams,
  targetRow = null,
  projectRow = null,
}: {
  auth: AuthContext | null;
  enqueue?: ReturnType<typeof vi.fn>;
  seedsQuota?: number;
  seedsUsed?: number;
  activeJobs?: Array<{ seedsRequested: number; seedsConsumed: number }>;
  maxConcurrent?: number;
  gpuSpendCapUsd?: number | string;
  gpuSpendUsd?: number | string;
  toolVersion?: string | null;
  toolAdapterVersion?: string | null;
  toolImageDigest?: string | null;
  toolCompute?: unknown;
  toolInputSchema?: unknown;
  toolDefaultParams?: unknown;
  targetRow?: {
    id: string;
    projectId?: string | null;
    hotspots?: unknown;
  } | null;
  projectRow?: { id: string } | null;
}) {
  const createMock = vi.fn().mockResolvedValue(createdJobRow());
  const updateMock = vi.fn().mockImplementation(async ({ where, data }) => ({
    ...createdJobRow(),
    id: where.id,
    ...data,
  }));
  const designCreateMany = vi.fn().mockResolvedValue({ count: 0 });
  const gpuSpendCreate = vi.fn().mockResolvedValue({});
  const gpuSpendUpdateMany = vi.fn().mockResolvedValue({ count: 1 });
  const executeRaw = vi.fn().mockResolvedValue(1);
  const targetFindFirst = vi.fn().mockResolvedValue(targetRow);
  const projectFindFirst = vi.fn().mockResolvedValue(projectRow);
  const withRlsUser = vi.fn(async (_prisma, userId, fn) => {
    if (auth) expect(userId).toBe(auth.userId);
    return fn({
      job: {
        create: createMock,
        update: updateMock,
        findMany: vi.fn().mockResolvedValue(activeJobs),
      },
      organization: {
        findUnique: vi.fn().mockResolvedValue({
          id: ORG_ID,
          seedsQuota,
          seedsUsed,
          gpuSpendCapUsd,
          gpuSpendUsd,
        }),
      },
      featureFlag: {
        findUnique: vi.fn().mockResolvedValue({
          orgId: ORG_ID,
          maxConcurrent,
          onCap: "block",
        }),
      },
      modalCredential: { findUnique: vi.fn().mockResolvedValue(null) },
      target: { findFirst: targetFindFirst },
      project: { findFirst: projectFindFirst },
      design: { createMany: designCreateMany },
      gpuSpend: {
        create: gpuSpendCreate,
        updateMany: gpuSpendUpdateMany,
      },
      $executeRawUnsafe: executeRaw,
      tool: {
        findUnique: vi.fn().mockResolvedValue({
          compute: toolCompute,
          ...(toolVersion === null ? {} : { version: toolVersion }),
          ...(toolAdapterVersion === null
            ? {}
            : { adapterVersion: toolAdapterVersion }),
          ...(toolImageDigest === null ? {} : { imageDigest: toolImageDigest }),
          ...(toolInputSchema === undefined
            ? {}
            : { inputSchema: toolInputSchema }),
          ...(toolDefaultParams === undefined
            ? {}
            : { defaultParams: toolDefaultParams }),
        }),
      },
    });
  });

  const ctx = createInnerContext({
    auth,
    prisma: {} as never,
    withRlsUser: withRlsUser as never,
    enqueueJob: enqueue,
  });
  return {
    ctx,
    createMock,
    updateMock,
    designCreateMany,
    gpuSpendUpdateMany,
    executeRaw,
    targetFindFirst,
    projectFindFirst,
    withRlsUser,
    enqueue,
  };
}

describe("jobs.submit", () => {
  it("rejects unauthenticated callers", async () => {
    const { ctx } = buildHarness({ auth: null });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it("accepts a pro-tier caller for a verified runnable tool", async () => {
    const { ctx, enqueue, createMock, executeRaw } = buildHarness({
      auth: makeAuth("pro"),
    });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.jobs.submit(REQUEST);

    expect(out.id).toBe("00000000-0000-4000-8000-0000000000ff");
    expect(out.status).toBe("queued");
    expect(out.etaSeconds).toBe(270);
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(enqueue).toHaveBeenCalledTimes(1);
    expect(executeRaw.mock.calls[0]?.[0]).toMatch(
      /gpu_spend_usd \+ \$1::numeric/,
    );
    const [queueName] = enqueue.mock.calls[0]!;
    expect(queueName).toBe("jobs-pro");
  });

  it("resolves a trusted workflow, reserves every stage, and enqueues one composite job", async () => {
    const { ctx, enqueue, createMock } = buildHarness({
      auth: makeAuth("pro"),
      toolCompute: { gpu: "A10", estSecondsPerDesign: 10 },
    });
    const caller = appRouter.createCaller(ctx);

    const out = await caller.jobs.submit({
      ...EXPERIMENTAL_REQUEST,
      workflowId: "binder-standard",
    });

    expect(out.toolId).toBe("rfdiffusion+proteinmpnn+boltz2");
    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          tool: "rfdiffusion+proteinmpnn+boltz2",
          params: expect.objectContaining({
            _papercraneWorkflow: expect.objectContaining({
              id: "binder-standard",
              version: 1,
              stages: expect.arrayContaining([
                expect.objectContaining({ toolId: "rfdiffusion" }),
                expect.objectContaining({ toolId: "proteinmpnn" }),
                expect.objectContaining({ toolId: "boltz2" }),
              ]),
            }),
          }),
        }),
      }),
    );
    expect(enqueue).toHaveBeenCalledWith(
      "jobs-pro",
      expect.objectContaining({ toolId: "rfdiffusion+proteinmpnn+boltz2" }),
    );
  });

  it("accepts an uploaded target owned by the caller's organization", async () => {
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
    });
    const caller = appRouter.createCaller(ctx);

    await caller.jobs.submit({
      ...REQUEST,
      request: {
        ...REQUEST.request,
        targetPdb: `orgs/${ORG_ID}/uploads/target.cif`,
      },
    });

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(enqueue).toHaveBeenCalledTimes(1);
  });

  it("rejects cross-org and traversal artifact keys before reads or writes", async () => {
    const invalidReferences = [
      {
        label: "target",
        patch: { targetPdb: "orgs/another-org/uploads/target.cif" },
      },
      {
        label: "partner",
        patch: {
          partnerPdb: `orgs/${ORG_ID}/uploads/../private/partner.cif`,
        },
      },
      {
        label: "ligand",
        patch: {
          toolParams: {
            ligand_sdf: `orgs/${ORG_ID}//uploads/ligand.sdf`,
          },
        },
      },
    ];

    for (const { label, patch } of invalidReferences) {
      const { ctx, createMock, enqueue, withRlsUser } = buildHarness({
        auth: makeAuth("pro"),
      });
      const caller = appRouter.createCaller(ctx);

      await expect(
        caller.jobs.submit({
          ...REQUEST,
          request: { ...REQUEST.request, ...patch },
        }),
      ).rejects.toThrow(new RegExp(`${label} artifact key`, "i"));
      expect(withRlsUser).not.toHaveBeenCalled();
      expect(createMock).not.toHaveBeenCalled();
      expect(enqueue).not.toHaveBeenCalled();
    }
  });

  it("uses the tool compute profile for the submitted ETA", async () => {
    const { ctx } = buildHarness({
      auth: makeAuth("pro"),
      toolCompute: {
        gpu: "A100-40GB",
        estSecondsPerDesign: 500,
      },
    });
    const caller = appRouter.createCaller(ctx);

    const out = await caller.jobs.submit(REQUEST);

    expect(out.etaSeconds).toBe(1_030);
  });

  it("persists owned target/project identity and saved hotspots", async () => {
    const targetId = "00000000-0000-4000-8000-0000000000b1";
    const projectId = "00000000-0000-4000-8000-0000000000c1";
    const { ctx, createMock, targetFindFirst, projectFindFirst } = buildHarness(
      {
        auth: makeAuth("pro"),
        targetRow: {
          id: targetId,
          projectId,
          hotspots: [{ chain: "A", residues: [12, 18] }],
        },
        projectRow: { id: projectId },
      },
    );
    const caller = appRouter.createCaller(ctx);

    await caller.jobs.submit({
      ...REQUEST,
      request: {
        ...REQUEST.request,
        toolParams: { targetId, projectId },
      },
    });

    expect(targetFindFirst).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: targetId, orgId: ORG_ID },
      }),
    );
    expect(projectFindFirst).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: projectId, orgId: ORG_ID },
      }),
    );
    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          targetId,
          projectId,
          params: expect.objectContaining({
            hotspots: [{ chain: "A", residues: [12, 18] }],
          }),
        }),
      }),
    );
  });

  it("rejects a target and project that do not belong together", async () => {
    const targetId = "00000000-0000-4000-8000-0000000000b1";
    const targetProjectId = "00000000-0000-4000-8000-0000000000c1";
    const requestedProjectId = "00000000-0000-4000-8000-0000000000c2";
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      targetRow: { id: targetId, projectId: targetProjectId },
      projectRow: { id: requestedProjectId },
    });
    const caller = appRouter.createCaller(ctx);

    await expect(
      caller.jobs.submit({
        ...REQUEST,
        request: {
          ...REQUEST.request,
          toolParams: { targetId, projectId: requestedProjectId },
        },
      }),
    ).rejects.toThrow(/target does not belong to the requested project/i);
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("accepts a statically integrated beta tool", async () => {
    const { ctx, createMock, withRlsUser, enqueue } = buildHarness({
      auth: makeAuth("pro"),
    });
    const caller = appRouter.createCaller(ctx);

    await caller.jobs.submit({ ...EXPERIMENTAL_REQUEST, toolId: "foldseek" });
    expect(withRlsUser).toHaveBeenCalled();
    expect(createMock).toHaveBeenCalled();
    expect(enqueue).toHaveBeenCalled();
  });

  it("rejects invalid manifest parameters before writing or enqueueing", async () => {
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      toolInputSchema: {
        type: "object",
        properties: {
          params: {
            type: "object",
            additionalProperties: false,
            properties: {
              exhaustiveness: { type: "integer", minimum: 1, maximum: 128 },
            },
          },
        },
      },
      toolDefaultParams: { exhaustiveness: 8 },
    });
    const caller = appRouter.createCaller(ctx);

    await expect(
      caller.jobs.submit({
        ...REQUEST,
        request: {
          ...REQUEST.request,
          toolParams: { exhaustiveness: 256 },
        },
      }),
    ).rejects.toThrow(/invalid tool parameters/i);
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("fails closed on a malformed embedded tool schema", async () => {
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      toolInputSchema: {
        type: "object",
        properties: { value: { $ref: "#/definitions/missing" } },
      },
    });
    const caller = appRouter.createCaller(ctx);

    await expect(caller.jobs.submit(REQUEST)).rejects.toMatchObject({
      code: "PRECONDITION_FAILED",
    });
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("rejects a catalogued tool whose implementation is still a stub", async () => {
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("frontier"),
    });
    const caller = appRouter.createCaller(ctx);

    await expect(
      caller.jobs.submit({ ...EXPERIMENTAL_REQUEST, toolId: "germinal" }),
    ).rejects.toThrow(/not yet runnable/i);
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("rejects a pro-tier caller for a frontier-only tool", async () => {
    const { ctx } = buildHarness({ auth: makeAuth("pro") });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(AF3_REQUEST)).rejects.toThrow(
      /forbidden|tier|allowlist|alphafold3/i,
    );
  });

  it("accepts a frontier-tier caller for alphafold3", async () => {
    const { ctx, enqueue } = buildHarness({ auth: makeAuth("frontier") });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(AF3_REQUEST);
    expect(enqueue).toHaveBeenCalledTimes(1);
    const [queueName] = enqueue.mock.calls[0]!;
    expect(queueName).toBe("jobs-frontier");
  });

  it("keeps Chai-1 behind the frontier license gate", async () => {
    const proHarness = buildHarness({ auth: makeAuth("pro") });
    await expect(
      appRouter.createCaller(proHarness.ctx).jobs.submit(CHAI1_REQUEST),
    ).rejects.toThrow(/forbidden|tier|allowlist|chai1/i);

    const frontierHarness = buildHarness({ auth: makeAuth("frontier") });
    await appRouter
      .createCaller(frontierHarness.ctx)
      .jobs.submit(CHAI1_REQUEST);
    expect(frontierHarness.enqueue).toHaveBeenCalledTimes(1);
  });

  it("rejects when seed quota is insufficient", async () => {
    const { ctx } = buildHarness({
      auth: makeAuth("free"),
      seedsQuota: 2,
      seedsUsed: 0, // request asks for 3 seeds
    });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(/quota|seed/i);
  });

  it("counts pending active jobs against the seed allocation", async () => {
    const { ctx } = buildHarness({
      auth: makeAuth("free"),
      seedsQuota: 5,
      seedsUsed: 1,
      activeJobs: [{ seedsRequested: 3, seedsConsumed: 1 }],
    });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(
      /allocation|seeds/i,
    );
  });

  it("rejects when the GPU spend cap would be breached", async () => {
    // Org has $0.01 of head-room left; even the cheapest tool projection
    // pushes it over the $50 cap. The pre-flight in jobs.submit should
    // throw FORBIDDEN with the canonical "GPU spend cap reached" message
    // before any job row is written.
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      gpuSpendCapUsd: 50,
      gpuSpendUsd: 49.99,
    });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(
      /gpu spend cap reached/i,
    );
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("allows submission when remaining budget covers the estimate", async () => {
    // Sanity counterpart: $50 cap and $0 spent should let a small job
    // through, proving the cap check doesn't false-positive at clean state.
    const { ctx, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      gpuSpendCapUsd: 50,
      gpuSpendUsd: 0,
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);
    expect(enqueue).toHaveBeenCalledTimes(1);
  });

  it("persists the tool's real version on the created job row", async () => {
    const { ctx, createMock } = buildHarness({
      auth: makeAuth("pro"),
      toolVersion: "1.2.3",
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);

    expect(createMock).toHaveBeenCalledTimes(1);
    const [{ data }] = createMock.mock.calls[0]! as [
      { data: Record<string, unknown> },
    ];
    expect(data.toolVersion).toBe("1.2.3");
    expect(data.toolVersion).not.toBe("0.0.0");
  });

  it("falls back to 0.0.0 only when the tool has no version", async () => {
    const { ctx, createMock } = buildHarness({
      auth: makeAuth("pro"),
      toolVersion: null,
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);

    const [{ data }] = createMock.mock.calls[0]! as [
      { data: Record<string, unknown> },
    ];
    expect(data.toolVersion).toBe("0.0.0");
  });

  it("persists the tool's adapter version and image digest for provenance", async () => {
    const { ctx, createMock } = buildHarness({
      auth: makeAuth("pro"),
      toolAdapterVersion: "a3",
      toolImageDigest: "sha256:abc123def456",
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);

    expect(createMock).toHaveBeenCalledTimes(1);
    const [{ data }] = createMock.mock.calls[0]! as [
      { data: Record<string, unknown> },
    ];
    expect(data.adapterVersion).toBe("a3");
    expect(data.imageDigest).toBe("sha256:abc123def456");
  });

  it("writes null adapterVersion / imageDigest when the tool carries none", async () => {
    const { ctx, createMock } = buildHarness({
      auth: makeAuth("pro"),
      toolAdapterVersion: null,
      toolImageDigest: null,
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);

    const [{ data }] = createMock.mock.calls[0]! as [
      { data: Record<string, unknown> },
    ];
    expect(data.adapterVersion).toBeNull();
    expect(data.imageDigest).toBeNull();
  });

  it("rejects when the requested seed count exceeds the per-job cap", async () => {
    // Beta guardrail: even with bounded fan-out, a 100-seed job creates too
    // much spend and artifact churn for one private-beta submission. It must
    // fail fast with BAD_REQUEST and never write a job row.
    const { ctx, createMock, enqueue } = buildHarness({
      auth: makeAuth("pro"),
      seedsQuota: 10000, // plenty of quota — the cap, not the quota, must trip
    });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(OVER_CAP_REQUEST)).rejects.toThrow(
      /exceeds the current per-job limit of 25/i,
    );
    expect(createMock).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("allows a submission whose seed count is at/under the per-job cap", async () => {
    // The default REQUEST asks for 3 seeds — well under the cap of 25.
    const { ctx, enqueue, createMock } = buildHarness({
      auth: makeAuth("pro"),
    });
    const caller = appRouter.createCaller(ctx);
    await caller.jobs.submit(REQUEST);
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(enqueue).toHaveBeenCalledTimes(1);
  });

  it("marks inline development designs synthetic and refunds GPU spend", async () => {
    process.env.WORKER_DEV_MODE = "true";
    const {
      ctx,
      updateMock,
      designCreateMany,
      gpuSpendUpdateMany,
      executeRaw,
      enqueue,
    } = buildHarness({ auth: makeAuth("pro") });
    const caller = appRouter.createCaller(ctx);

    const out = await caller.jobs.submit(REQUEST);

    expect(out.status).toBe("succeeded");
    expect(out.completedDesigns).toBe(3);
    expect(enqueue).not.toHaveBeenCalled();
    expect(updateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          seedsConsumed: 3,
          status: "succeeded",
        }),
      }),
    );
    const [{ data }] = designCreateMany.mock.calls[0]! as [
      { data: Array<Record<string, unknown>> },
    ];
    expect(data).toHaveLength(3);
    expect(data.every((row) => row.provenance === "synthetic")).toBe(true);
    expect(gpuSpendUpdateMany).toHaveBeenCalledWith({
      where: { jobId: out.id },
      data: { actualUsd: expect.anything(), secondsActual: 0 },
    });
    expect(executeRaw.mock.calls.at(-1)?.[0]).toMatch(
      /GREATEST\(0, gpu_spend_usd - \$1::numeric\)/,
    );
  });

  it("honours the PAPERCRANE_MAX_SEEDS_PER_JOB env override", async () => {
    const prev = process.env.PAPERCRANE_MAX_SEEDS_PER_JOB;
    process.env.PAPERCRANE_MAX_SEEDS_PER_JOB = "2"; // REQUEST asks for 3 seeds
    try {
      const { ctx, createMock } = buildHarness({ auth: makeAuth("pro") });
      const caller = appRouter.createCaller(ctx);
      await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(
        /exceeds the current per-job limit of 2/i,
      );
      expect(createMock).not.toHaveBeenCalled();
    } finally {
      if (prev === undefined) delete process.env.PAPERCRANE_MAX_SEEDS_PER_JOB;
      else process.env.PAPERCRANE_MAX_SEEDS_PER_JOB = prev;
    }
  });

  it("rejects when the org concurrency limit is reached", async () => {
    const { ctx } = buildHarness({
      auth: makeAuth("pro"),
      activeJobs: [{ seedsRequested: 3, seedsConsumed: 0 }],
      maxConcurrent: 1,
    });
    const caller = appRouter.createCaller(ctx);
    await expect(caller.jobs.submit(REQUEST)).rejects.toThrow(/concurrency/i);
  });
});

describe("jobs.logs", () => {
  it("returns ordered logs only after verifying org ownership", async () => {
    const jobFindFirst = vi.fn().mockResolvedValue({ id: "job-1" });
    const logFindMany = vi.fn().mockResolvedValue([
      {
        id: "log-1",
        level: "info",
        event: "status",
        message: "Job status: running",
        metadata: { status: "running" },
        createdAt: new Date("2026-07-13T18:00:00Z"),
      },
    ]);
    const ctx = createInnerContext({
      auth: makeAuth("pro"),
      prisma: {} as never,
      withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
        fn({
          job: { findFirst: jobFindFirst },
          jobLog: { findMany: logFindMany },
        } as never),
      ) as never,
    });

    const result = await appRouter.createCaller(ctx).jobs.logs({
      id: "job-1",
      after: "2026-07-13T17:00:00.000Z",
    });

    expect(jobFindFirst).toHaveBeenCalledWith({
      where: { id: "job-1", orgId: ORG_ID },
      select: { id: true },
    });
    expect(logFindMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: {
          jobId: "job-1",
          createdAt: { gte: new Date("2026-07-13T17:00:00.000Z") },
        },
        take: 200,
      }),
    );
    expect(result.items[0]).toMatchObject({
      id: "log-1",
      event: "status",
      createdAt: "2026-07-13T18:00:00.000Z",
    });
  });

  it("does not query logs for a job outside the caller org", async () => {
    const logFindMany = vi.fn();
    const ctx = createInnerContext({
      auth: makeAuth("pro"),
      prisma: {} as never,
      withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
        fn({
          job: { findFirst: vi.fn().mockResolvedValue(null) },
          jobLog: { findMany: logFindMany },
        } as never),
      ) as never,
    });

    await expect(
      appRouter.createCaller(ctx).jobs.logs({ id: "other-org-job" }),
    ).rejects.toThrow(/job not found/i);
    expect(logFindMany).not.toHaveBeenCalled();
  });
});

describe("jobs.get", () => {
  it("returns provenance fields (version, adapter, image digest, params)", async () => {
    const jobRow = {
      id: "00000000-0000-4000-8000-0000000000ff",
      orgId: ORG_ID,
      tool: "rfdiffusion",
      toolVersion: "1.2.3",
      adapterVersion: "a3",
      imageDigest: "sha256:abc123def456",
      params: {
        request: { targetPdb: "1ABC", seeds: [0, 1, 2], numDesigns: 3 },
      },
      seedsRequested: 3,
      seedsConsumed: 0,
      status: "queued",
      attempt: 2,
      heartbeatAt: new Date("2026-04-23T12:01:00Z"),
      error: {
        code: "NETWORK_TIMEOUT",
        message: "provider timed out",
        retryable: true,
        completedSeeds: 1,
      },
      submittedAt: new Date("2026-04-23T12:00:00Z"),
    };
    const findFirst = vi.fn().mockResolvedValue(jobRow);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ job: { findFirst } }),
    );
    const ctx = createInnerContext({
      auth: makeAuth("pro"),
      prisma: {} as never,
      withRlsUser: withRlsUser as never,
    });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.jobs.get({ id: jobRow.id });

    expect(out.toolVersion).toBe("1.2.3");
    expect(out.adapterVersion).toBe("a3");
    expect(out.imageDigest).toBe("sha256:abc123def456");
    expect(out).toMatchObject({
      attempt: 2,
      heartbeatAt: "2026-04-23T12:01:00.000Z",
      errorCode: "NETWORK_TIMEOUT",
      errorRetryable: true,
      errorCompletedSeeds: 1,
    });
    expect(out.params).toMatchObject({
      request: { targetPdb: "1ABC" },
    });
  });
});

describe("jobs.cancel", () => {
  function cancellationHarness(status: string) {
    const row = { ...createdJobRow(), status };
    const updateMany = vi.fn(async ({ where, data }) => {
      const matches = typeof where.status === "string"
        ? row.status === where.status : where.status.in.includes(row.status);
      if (matches) Object.assign(row, data);
      return { count: matches ? 1 : 0 };
    });
    const findFirst = vi.fn().mockImplementation(async () => row);
    const publish = vi.fn().mockResolvedValue(undefined);
    const releaseReservation = vi.fn().mockResolvedValue(1);
    const withRlsUser = vi.fn(async (_p, _uid, fn) => fn({ job: { updateMany, findFirst }, $executeRawUnsafe: releaseReservation }));
    const caller = appRouter.createCaller(createInnerContext({
      auth: makeAuth("pro"), prisma: {} as never,
      withRlsUser: withRlsUser as never, publishCancel: publish,
    }));
    return { caller, row, updateMany, findFirst, publish, releaseReservation };
  }

  it("cancels queued work without a live worker", async () => {
    const h = cancellationHarness("queued");
    const out = await h.caller.jobs.cancel({ jobId: "job-1" });
    expect(out.status).toBe("cancelled");
    expect(h.row).toHaveProperty("completedAt");
    expect(h.publish).not.toHaveBeenCalled();
    await h.caller.jobs.cancel({ jobId: "job-1" });
    expect(h.releaseReservation).toHaveBeenCalledTimes(1);
    expect(h.updateMany.mock.calls[0]?.[0].where).toEqual({ id: "job-1", orgId: ORG_ID, status: "queued" });
  });

  it("signals active work after persisting the cancellation", async () => {
    const h = cancellationHarness("running");
    expect((await h.caller.jobs.cancel({ jobId: "job-1" })).status).toBe("cancelling");
    expect(h.publish).toHaveBeenCalledWith("job-1");
  });

  it.each(["succeeded", "partial", "failed", "cancelled", "purged"])("preserves terminal %s jobs", async status => {
    const h = cancellationHarness(status);
    expect((await h.caller.jobs.cancel({ jobId: "job-1" })).status).toBe(status);
    expect(h.publish).not.toHaveBeenCalled();
  });

  it("does not expose another organization's job", async () => {
    const h = cancellationHarness("queued");
    h.findFirst.mockResolvedValue(null);
    await expect(h.caller.jobs.cancel({ jobId: "foreign-job" })).rejects.toMatchObject({ code: "NOT_FOUND" });
    expect(h.findFirst).toHaveBeenCalledWith({ where: { id: "foreign-job", orgId: ORG_ID } });
  });
});

it("lists only the requested project within the authenticated organization", async () => {
  const projectId = '00000000-0000-4000-8000-000000000123';
  const findMany = vi.fn().mockResolvedValue([{ ...createdJobRow(), projectId }]);
  const caller = appRouter.createCaller(createInnerContext({ auth: makeAuth('pro'), prisma: {} as never,
    withRlsUser: vi.fn(async (_p, _u, fn) => fn({ job: { findMany } })) as never }));
  const result = await caller.jobs.list({ projectId });
  expect(findMany).toHaveBeenCalledWith(expect.objectContaining({ where: { orgId: ORG_ID, projectId } }));
  expect(result.items[0]?.projectId).toBe(projectId);
});
