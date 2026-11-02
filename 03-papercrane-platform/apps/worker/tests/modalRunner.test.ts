import { resolve } from "node:path";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import {
  ModalProviderUnavailableError,
  ModalOutputContractError,
  modalLaneInput,
  normalizeModalPoolConcurrency,
  runViaModal,
  spawnViaModal,
  spawnViaModalPool,
} from "../src/adapters/_modalRunner";

const fakeModal = resolve(process.cwd(), "tests/fixtures/fake-modal.sh");

describe("Modal CLI runner", () => {
  it("streams a seed and parses a final done event without a trailing newline", async () => {
    const output = await runViaModal(
      "esm2",
      { jobId: "j", seeds: [7], params: {} },
      { modalBin: fakeModal, timeoutMs: 2_000 },
    );

    expect(output.designs).toEqual([
      {
        seed: 7,
        sequence: "M",
        structureKey: "orgs/o/jobs/j/designs/7.cif",
        metrics: { score: 0.9 },
      },
    ]);
    expect(output.meta?.summary).toEqual({ completed: 1 });
  });

  it("cancels an attached CLI while it is still producing events", async () => {
    const run = spawnViaModal(
      "esm2",
      { jobId: "j", seeds: [7], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        env: { ...process.env, FAKE_MODAL_HANG: "1" },
      },
    );
    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).resolves.toMatchObject({
      value: { type: "seed", seed: 7 },
    });
    await run.cancel();
    await expect(iterator.next()).resolves.toEqual({
      value: undefined,
      done: true,
    });
  });

  it("force-kills a CLI that ignores graceful cancellation", async () => {
    const run = spawnViaModal(
      "esm2",
      { jobId: "stuck", seeds: [7], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        terminationGraceMs: 25,
        env: {
          ...process.env,
          FAKE_MODAL_HANG: "1",
          FAKE_MODAL_IGNORE_TERM: "1",
        },
      },
    );
    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).resolves.toMatchObject({
      value: { type: "seed", seed: 7 },
    });

    await run.cancel();

    await expect(iterator.next()).resolves.toEqual({
      value: undefined,
      done: true,
    });
  });

  it("classifies a Modal endpoint outage as retryable infrastructure failure", async () => {
    const run = spawnViaModal(
      "esm2",
      { jobId: "j", seeds: [7], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        env: { ...process.env, FAKE_MODAL_CONNECTION_ERROR: "1" },
      },
    );

    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).rejects.toMatchObject({
      name: ModalProviderUnavailableError.name,
      code: "PROVIDER_UNAVAILABLE",
      retryable: true,
    });
  });

  it("merges bounded seed lanes into one event stream", async () => {
    const run = spawnViaModalPool(
      "esm2",
      { jobId: "pooled", seeds: [1, 2, 3], params: {} },
      { modalBin: fakeModal, timeoutMs: 2_000, concurrency: 2 },
    );
    const events = [];
    for await (const event of run.events) events.push(event);

    expect(events.filter((event) => event.type === "seed")).toHaveLength(3);
    expect(
      events
        .filter((event) => event.type === "seed")
        .map((event) => (event.type === "seed" ? event.seed : -1))
        .sort((a, b) => a - b),
    ).toEqual([1, 2, 3]);
    expect(events.at(-1)).toMatchObject({
      type: "done",
      summary: { completed: 3, requested: 3, concurrency: 2 },
    });
  });

  it("reuses one Modal process per lane instead of reloading per seed", async () => {
    const dir = mkdtempSync(resolve(tmpdir(), "papercrane-modal-pool-"));
    const invocationLog = resolve(dir, "invocations.log");
    try {
      const run = spawnViaModalPool(
        "esm2",
        { jobId: "pooled", seeds: [1, 2, 3, 4, 5], params: {} },
        {
          modalBin: fakeModal,
          timeoutMs: 2_000,
          concurrency: 2,
          env: { ...process.env, FAKE_MODAL_INVOCATION_LOG: invocationLog },
        },
      );
      const seeds: number[] = [];
      for await (const event of run.events) {
        if (event.type === "seed") seeds.push(event.seed);
      }

      expect(seeds.sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5]);
      expect(readFileSync(invocationLog, "utf8").trim().split("\n")).toHaveLength(2);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("clamps invalid and excessive pool sizes", () => {
    expect(normalizeModalPoolConcurrency(Number.NaN, 4)).toBe(1);
    expect(normalizeModalPoolConcurrency(0, 4)).toBe(1);
    expect(normalizeModalPoolConcurrency(99, 20)).toBe(8);
    expect(normalizeModalPoolConcurrency(8, 3)).toBe(3);
  });

  it("forces every seed lane to one design across legacy parameter shapes", () => {
    expect(
      modalLaneInput(
        {
          jobId: "lane",
          seeds: [3, 4],
          params: {
            numDesigns: 8,
            num_designs: 8,
            params: { numDesigns: 8 },
            toolParams: { num_designs: 8, temperature: 0.2 },
          },
        },
        4,
      ),
    ).toMatchObject({
      seeds: [4],
      params: {
        numDesigns: 1,
        num_designs: 1,
        num_seq_per_target: 1,
        params: {
          numDesigns: 1,
          num_designs: 1,
          num_seq_per_target: 1,
        },
        toolParams: {
          numDesigns: 1,
          num_designs: 1,
          num_seq_per_target: 1,
          temperature: 0.2,
        },
      },
    });
  });

  it("uses isolated one-seed lanes even when parallelism is one", async () => {
    const run = spawnViaModalPool(
      "esm2",
      { jobId: "serial-pool", seeds: [3, 4], params: { numDesigns: 2 } },
      { modalBin: fakeModal, timeoutMs: 2_000, concurrency: 1 },
    );
    const seeds: number[] = [];
    for await (const event of run.events) {
      if (event.type === "seed") seeds.push(event.seed);
    }
    expect(seeds).toEqual([3, 4]);
  });

  it("fails a pool lane that completes without its requested seed", async () => {
    const run = spawnViaModalPool(
      "esm2",
      { jobId: "missing-seed", seeds: [1, 2], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        concurrency: 2,
        env: { ...process.env, FAKE_MODAL_SKIP_SEED: "1" },
      },
    );

    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).rejects.toMatchObject({
      name: ModalOutputContractError.name,
      code: "INVALID_OUTPUT",
      retryable: false,
    });
  });

  it("fails a pool lane that emits a different seed", async () => {
    const run = spawnViaModalPool(
      "esm2",
      { jobId: "wrong-seed", seeds: [1, 2], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        concurrency: 2,
        env: { ...process.env, FAKE_MODAL_SEED_OVERRIDE: "999" },
      },
    );

    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).rejects.toMatchObject({
      name: ModalOutputContractError.name,
      code: "INVALID_OUTPUT",
    });
  });

  it("discards buffered lane events when a pooled run is cancelled", async () => {
    const run = spawnViaModalPool(
      "esm2",
      { jobId: "cancel-pool", seeds: [1, 2, 3], params: {} },
      {
        modalBin: fakeModal,
        timeoutMs: 2_000,
        terminationGraceMs: 100,
        concurrency: 2,
        env: { ...process.env, FAKE_MODAL_HANG: "1" },
      },
    );
    const iterator = run.events[Symbol.asyncIterator]();
    await expect(iterator.next()).resolves.toMatchObject({
      value: { type: "seed" },
    });
    await run.cancel();
    await expect(iterator.next()).resolves.toEqual({
      value: undefined,
      done: true,
    });
  });
});
