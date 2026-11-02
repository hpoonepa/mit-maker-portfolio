import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { createWriteStream, existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(WEB_ROOT, "../../..");
const PYTHON = process.env.SQUASHVISION_E2E_PYTHON ?? resolve(REPOSITORY_ROOT, "src/squashvision/backend/.venv/bin/python");
const LAUNCHER = resolve(REPOSITORY_ROOT, "src/squashvision/launcher.py");
const DATA_DIR = resolve(process.env.SQUASHVISION_E2E_DATA_DIR ?? resolve(WEB_ROOT, ".playwright-review-data"));
const FIXTURE_DIR = mkdtempSync(resolve(tmpdir(), "squashvision-e2e-fixture-"));
const BASE_URL = process.env.SQUASHVISION_E2E_BASE_URL ?? "http://127.0.0.1:8765";
const PRODUCT_URL = new URL(BASE_URL);
if (PRODUCT_URL.protocol !== "http:" || PRODUCT_URL.hostname !== "127.0.0.1" || PRODUCT_URL.port === "") {
  throw new Error("SQUASHVISION_E2E_BASE_URL must be an explicit 127.0.0.1 HTTP port");
}
const API_PORT = PRODUCT_URL.port;
const LAUNCHER_LOG_PATH = resolve(FIXTURE_DIR, "launcher.log");
let launcher: ChildProcessWithoutNullStreams | null = null;
const launcherLog = createWriteStream(LAUNCHER_LOG_PATH, { flags: "a" });
let launcherReady = false;
let launcherOutputTail = "";

function delay(milliseconds: number): Promise<void> {
  const { promise, resolve: resolveDelay } = Promise.withResolvers<void>();
  setTimeout(resolveDelay, milliseconds);
  return promise;
}

async function flushLauncherLog(): Promise<void> {
  await new Promise<void>((resolveFlush, rejectFlush) => {
    launcherLog.write("", (error) => {
      if (error) rejectFlush(error);
      else resolveFlush();
    });
  });
}

function objectValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("expected an object");
  }
  return value as Record<string, unknown>;
}

function optionalObject(value: Record<string, unknown>, name: string): Record<string, unknown> | null {
  const candidate = value[name];
  return candidate === undefined || candidate === null ? null : objectValue(candidate);
}

function healthIsReady(payload: Record<string, unknown>, launcherSignaledReady: boolean): boolean {
  const ffmpeg = optionalObject(payload, "ffmpeg");
  const worker = optionalObject(payload, "worker");
  return (
    (payload.status === "ready" || payload.status === "degraded")
    && ffmpeg?.status === "ready"
    && (worker?.status === "ready" || launcherSignaledReady)
  );
}

function observeLauncherOutput(chunk: Buffer): void {
  launcherOutputTail = `${launcherOutputTail}${chunk.toString("utf8")}`.slice(-1_024);
  if (launcherOutputTail.includes(`SquashVision ready at ${BASE_URL}/`)) {
    launcherReady = true;
  }
}


async function waitForHealth(timeoutMs = 60_000): Promise<void> {
  const deadline = performance.now() + timeoutMs;
  let lastError: unknown = null;
  while (performance.now() < deadline) {
    if (launcher?.exitCode !== null) throw new Error(`launcher exited before health readiness: ${launcher?.exitCode}`);
    try {
      const response = await fetch(`${BASE_URL}/api/v1/health`);
      if (response.ok) {
        const payload = objectValue(await response.json());
        if (healthIsReady(payload, launcherReady)) return;
      }
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }
  throw new Error(`launcher health timed out: ${String(lastError)}`);
}

async function startLauncher(): Promise<void> {
  launcherReady = false;
  launcherOutputTail = "";
  launcher = spawn(
    PYTHON,
    [
      LAUNCHER,
      "--data-dir", DATA_DIR,
      "--api-port", API_PORT,
      "--static-dir", resolve(WEB_ROOT, "dist"),
      "--startup-timeout", "60",
      "--shutdown-timeout", "10",
      "--no-browser",
    ],
    { cwd: REPOSITORY_ROOT, env: process.env },
  );
  launcher.stdout.on("data", observeLauncherOutput);
  launcher.stdout.pipe(launcherLog, { end: false });
  launcher.stderr.pipe(launcherLog, { end: false });
  await waitForHealth();
}

async function stopLauncher(): Promise<number[]> {
  const running = launcher;
  if (running === null || running.exitCode !== null) return [];
  const heartbeatPath = resolve(DATA_DIR, ".worker-heartbeat.json");
  let workerPid = 0;
  if (existsSync(heartbeatPath)) {
    const heartbeat = objectValue(JSON.parse(readFileSync(heartbeatPath, "utf8")));
    if (typeof heartbeat.pid === "number") workerPid = heartbeat.pid;
  }
  const childPids = workerPid > 0 ? [workerPid] : [];
  running.kill("SIGTERM");
  const { promise: exitPromise, resolve: resolveExit, reject: rejectExit } = Promise.withResolvers<void>();
  const timer = setTimeout(() => rejectExit(new Error("launcher did not stop in 20 seconds")), 20_000);
  running.once("exit", () => { clearTimeout(timer); resolveExit(); });
  await exitPromise;
  launcher = null;
  for (const pid of childPids) {
    expect(() => process.kill(pid, 0)).toThrow();
  }
  return childPids;
}

interface DurableJobSnapshot {
  id: string;
  state: string;
  completedChunks: number;
  plannedChunks: number;
  version: number;
  heartbeatAt: string | null;
}

async function jobSnapshot(matchId: string): Promise<DurableJobSnapshot> {
  const response = await fetch(`${BASE_URL}/api/v1/matches/${encodeURIComponent(matchId)}`);
  const detail = objectValue(await response.json());
  const latestJob = optionalObject(detail, "latestJob");
  if (
    latestJob === null
    || typeof latestJob.id !== "string"
    || typeof latestJob.state !== "string"
    || typeof latestJob.version !== "number"
    || (latestJob.heartbeatAt !== null && typeof latestJob.heartbeatAt !== "string")
  ) {
    throw new TypeError("durable job snapshot is unavailable");
  }
  const progress = optionalObject(latestJob, "progress");
  return {
    id: latestJob.id,
    state: latestJob.state,
    completedChunks: typeof progress?.completedChunks === "number" ? progress.completedChunks : 0,
    plannedChunks: typeof progress?.plannedChunks === "number" ? progress.plannedChunks : 0,
    version: latestJob.version,
    heartbeatAt: latestJob.heartbeatAt,
  };
}

async function jobDetail(jobId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${BASE_URL}/api/v1/jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(`job detail request failed with HTTP ${response.status}`);
  }
  return objectValue(await response.json());
}

async function throwIfTerminal(snapshot: DurableJobSnapshot): Promise<void> {
  if (snapshot.state !== "failed" && snapshot.state !== "cancelled") return;
  const detail = await jobDetail(snapshot.id);
  throw new Error(
    `analysis entered terminal ${snapshot.state} state: ${JSON.stringify(detail)}`,
  );
}

async function waitForLiveRestartOrTerminal(
  matchId: string,
  interrupted: DurableJobSnapshot,
  timeoutMs: number,
): Promise<void> {
  const deadline = performance.now() + timeoutMs;
  let latest: DurableJobSnapshot | null = null;
  while (performance.now() < deadline) {
    latest = await jobSnapshot(matchId);
    if (latest.id !== interrupted.id) {
      throw new Error(`restart changed durable job id from ${interrupted.id} to ${latest.id}`);
    }
    await throwIfTerminal(latest);
    const heartbeatAdvanced = latest.heartbeatAt !== null
      && (interrupted.heartbeatAt === null || Date.parse(latest.heartbeatAt) > Date.parse(interrupted.heartbeatAt));
    if (
      latest.state === "running"
      && latest.version > interrupted.version
      && heartbeatAdvanced
    ) {
      return;
    }
    await delay(250);
  }
  throw new Error(
    `restarted job did not publish live RUNNING evidence before timeout; latest snapshot: ${JSON.stringify(latest)}`,
  );
}

async function waitForAnalysisOrTerminal(
  page: Page,
  matchId: string,
  timeoutMs: number,
): Promise<void> {
  const viewAnalysis = page.getByRole("link", { name: "View analysis" });
  const deadline = performance.now() + timeoutMs;
  let latest: DurableJobSnapshot | null = null;
  while (performance.now() < deadline) {
    if (await viewAnalysis.isVisible().catch(() => false)) return;
    latest = await jobSnapshot(matchId);
    await throwIfTerminal(latest);
    await delay(250);
  }
  throw new Error(
    `analysis did not expose View analysis before timeout; latest snapshot: ${JSON.stringify(latest)}`,
  );
}

function shotTypeCount(
  report: Record<string, unknown>,
  shotType: string,
): number {
  const sections = objectValue(report.sections);
  const shots = objectValue(sections.shots);
  const payload = objectValue(shots.payload);
  const players = objectValue(payload.players);
  let total = 0;
  for (const candidate of Object.values(players)) {
    const player = objectValue(candidate);
    const types = optionalObject(player, "types");
    if (types === null || types[shotType] === undefined) continue;
    const aggregate = objectValue(types[shotType]);
    if (
      typeof aggregate.count !== "number"
      || !Number.isSafeInteger(aggregate.count)
      || aggregate.count < 0
    ) {
      throw new TypeError("shot type count is invalid");
    }
    total += aggregate.count;
  }
  return total;
}
test("readiness rejects a degraded worker until the launcher emits its ready signal", () => {
  const degraded = {
    status: "degraded",
    ffmpeg: { status: "ready" },
    worker: { status: "unavailable" },
  };
  expect(healthIsReady(degraded, false)).toBe(false);
  expect(healthIsReady(degraded, true)).toBe(true);
});

test.describe("full local workflow", () => {

test.beforeAll(async () => {
  if (!existsSync(PYTHON)) throw new Error(`SquashVision backend Python is unavailable: ${PYTHON}`);
  execFileSync(PYTHON, [resolve(REPOSITORY_ROOT, "scripts/make_squash_fixture.py"), FIXTURE_DIR], {
    cwd: REPOSITORY_ROOT,
    stdio: "pipe",
  });
  await startLauncher();
});

test.afterEach(async ({}, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  await flushLauncherLog();
  await testInfo.attach("launcher.log", {
    path: LAUNCHER_LOG_PATH,
    contentType: "text/plain",
  });
});

test.afterAll(async () => {
  await stopLauncher();
  launcherLog.end();
  rmSync(FIXTURE_DIR, { recursive: true, force: true });
});

test("upload, recover durable processing, correct, export, persist, and delete", async ({ page }, testInfo) => {
  test.setTimeout(45 * 60 * 1000);
  const existingResponse = await page.request.get("/api/v1/matches?limit=100");
  expect(existingResponse.ok()).toBe(true);
  const existingPage = objectValue(await existingResponse.json());
  if (!Array.isArray(existingPage.items)) throw new TypeError("existing match page is invalid");
  for (const candidate of existingPage.items) {
    const existing = objectValue(candidate);
    if (typeof existing.id !== "string") throw new TypeError("existing match id is invalid");
    const removed = await page.request.delete(
      `/api/v1/matches/${encodeURIComponent(existing.id)}`,
    );
    expect(removed.ok()).toBe(true);
  }
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Matches", exact: true })).toBeVisible();

  const installModels = page.getByRole("button", { name: "Install local models" });
  if (await installModels.isVisible().catch(() => false)) {
    await installModels.click();
    await expect(page.getByText("Required models ready")).toBeVisible({ timeout: 10 * 60 * 1000 });
  }
  const modelStates = await page.request.get("/api/v1/models");
  expect(modelStates.ok()).toBe(true);
  const requiredModels = ((await modelStates.json()) as Array<{ name: string; required: boolean; state: string }>)
    .filter((model) => model.required);
  expect(requiredModels.length).toBeGreaterThan(0);
  for (const model of requiredModels) {
    if (model.state === "ready") continue;
    let finalStatus = 0;
    let finalBody = "";
    let ready = false;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const ensured = await page.request.post(
        `/api/v1/models/${encodeURIComponent(model.name)}/ensure`,
      );
      finalStatus = ensured.status();
      finalBody = await ensured.text();
      if (ensured.ok()) {
        try {
          const parsed: unknown = JSON.parse(finalBody);
          ready =
            typeof parsed === "object" &&
            parsed !== null &&
            "state" in parsed &&
            typeof parsed.state === "string" &&
            parsed.state === "ready";
        } catch {
          ready = false;
        }
      }
      if (ready) break;
      if (attempt < 2) await delay(500 * (attempt + 1));
    }
    if (!ready) {
      throw new Error(
        `Model ${model.name} did not become ready after 3 attempts; final HTTP ${finalStatus}: ${finalBody}`,
      );
    }
  }
  await expect
    .poll(async () => {
      const response = await page.request.get("/api/v1/models");
      if (!response.ok()) return false;
      const states = (await response.json()) as Array<{ name: string; required: boolean; state: string }>;
      return states.filter((model) => model.required).every((model) => model.state === "ready");
    })
    .toBe(true);
  await page.screenshot({ path: testInfo.outputPath("01-library-model-ready.png"), fullPage: true });

  await page.getByLabel("Choose one match video").setInputFiles(resolve(FIXTURE_DIR, "squash_review_fixture.mp4"));
  await page.getByLabel("Match title").fill("Task 16 recovery match");
  await page.getByLabel("Player A").fill("Ada");
  await page.getByLabel("Player B").fill("Bea");
  await page.getByRole("button", { name: "Upload match" }).click();
  const uploadedRow = page.getByRole(
    "listitem",
    { name: /Task 16 recovery match/ },
  );
  await expect(uploadedRow).toBeVisible();
  await uploadedRow.getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/matches\/[^/]+\/setup/);
  const matchId = page.url().match(/\/matches\/([^/]+)\/setup/)?.[1];
  if (matchId === undefined) throw new Error("uploaded match id was not present in the setup URL");

  const calibrationResponse = await page.request.put(
    `/api/v1/matches/${encodeURIComponent(matchId)}/calibration`,
    {
      data: {
        expectedRevision: 0,
        frameSize: { width: 1280, height: 720 },
        keypoints: [
          { label: "front-left", image: { x: 70, y: 45 }, court: { xM: 0, yM: 0 } },
          { label: "front-right", image: { x: 1210, y: 45 }, court: { xM: 6.4, yM: 0 } },
          { label: "back-right", image: { x: 1210, y: 675 }, court: { xM: 6.4, yM: 9.75 } },
          { label: "back-left", image: { x: 70, y: 675 }, court: { xM: 0, yM: 9.75 } },
        ],
      },
    },
  );
  expect(calibrationResponse.ok()).toBe(true);
  const calibration = objectValue(await calibrationResponse.json());
  const calibrationResult = objectValue(calibration.result);
  expect(calibrationResult.calibrated).toBe(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Calibrate the court" })).toBeVisible();
  await page.getByRole("button", { name: "Move front-left calibration point" }).press("ArrowRight");
  const calibrationSaved = page.waitForResponse((response) => (
    response.url().endsWith(`/matches/${matchId}/calibration`)
    && response.request().method() === "PUT"
  ));
  await page.getByRole("button", { name: "Save court" }).click();
  expect((await calibrationSaved).ok()).toBe(true);
  const calibrationDetails = page.locator("details").filter({ hasText: "Calibration quality and available measurements" });
  await expect(calibrationDetails).toHaveCount(1);
  await expect(calibrationDetails).not.toHaveAttribute("open", "");
  await calibrationDetails.locator("summary").click();
  await expect(calibrationDetails).toHaveAttribute("open", "");
  await expect(calibrationDetails.getByText(/Speed (available|unavailable)/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("02-calibration.png"), fullPage: true });

  await page.getByRole("button", { name: "Start analysis" }).click();
  await expect(page).toHaveURL(new RegExp(`/matches/${matchId}/processing`));
  await expect.poll(async () => {
    const snapshot = await jobSnapshot(matchId);
    return (
      snapshot.state === "running"
      && snapshot.completedChunks >= 1
      && snapshot.completedChunks < snapshot.plannedChunks
    ) ? "interruptible" : `${snapshot.state}:${snapshot.completedChunks}/${snapshot.plannedChunks}`;
  }, { timeout: 5 * 60 * 1000 }).toBe("interruptible");
  const interrupted = await jobSnapshot(matchId);

  await stopLauncher();
  await expect.poll(async () => fetch(`${BASE_URL}/api/v1/health`).then(() => "up").catch(() => "down"), { timeout: 20_000 }).toBe("down");
  await startLauncher();
  await waitForLiveRestartOrTerminal(matchId, interrupted, 5 * 60 * 1000);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForAnalysisOrTerminal(page, matchId, 30 * 60 * 1000);
  await page.getByRole("link", { name: "View analysis" }).click();
  await expect(page.getByRole("heading", { name: "Task 16 recovery match analysis" })).toBeVisible();

  const reportSections = [
    { id: "overview", label: "Overview" },
    { id: "shots", label: "Shots" },
    { id: "rallies", label: "Rallies" },
    { id: "movement", label: "Movement" },
    { id: "errors", label: "Errors" },
    { id: "trajectory", label: "Trajectory" },
    { id: "head-to-head", label: "Head-to-head" },
    { id: "coaching", label: "Coaching" },
  ] as const;
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    if (viewport.width >= 768) {
      for (const section of reportSections) {
        await page.getByRole("tab", { name: section.label }).click();
        await expect(page.getByRole("tab", { name: section.label })).toHaveAttribute("aria-selected", "true");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      }
      await page.getByRole("tab", { name: "Overview" }).click();
    } else {
      const reportSection = page.getByRole("combobox", { name: "Report section" });
      await expect(reportSection).toBeVisible();
      for (const section of reportSections) {
        await reportSection.selectOption(section.id);
        await expect(reportSection).toHaveValue(section.id);
        const panel = page.locator(`#report-panel-${section.id}`);
        await expect(panel).toHaveAttribute("role", "tabpanel");
        await expect(panel.locator(".report-view, .report-unavailable").first()).toBeVisible();
        await panel.scrollIntoViewIfNeeded();
        const panelBox = await panel.boundingBox();
        expect(panelBox).not.toBeNull();
        expect(panelBox?.x).toBeGreaterThanOrEqual(0);
        expect((panelBox?.x ?? 0) + (panelBox?.width ?? 0)).toBeLessThanOrEqual(viewport.width);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      }
      await reportSection.selectOption("overview");
    }
    await page.screenshot({
      path: testInfo.outputPath(`03-analysis-after-restart-${viewport.width}.png`),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  const revisionSelect = page.getByLabel("Report revision");
  const initialRevision = Number(await revisionSelect.inputValue());
  const beforeReportResponse = await page.request.get(
    `/api/v1/matches/${encodeURIComponent(matchId)}/reports/${initialRevision}`,
  );
  expect(beforeReportResponse.ok()).toBe(true);
  const beforeReport = objectValue(await beforeReportResponse.json());
  const beforeSections = objectValue(beforeReport.sections);
  const beforeShots = objectValue(beforeSections.shots);
  const beforeShotPayload = JSON.stringify(beforeShots.payload);
  if (typeof beforeShots.hash !== "string") throw new TypeError("shot section hash is invalid");

  const correctionSelect = page.locator(".correction-editor select").first();
  await expect(correctionSelect).toBeVisible();
  let correctionOptions = await correctionSelect.locator("option").allTextContents();
  for (let index = 0; index < 50 && !correctionOptions.includes("Change primary shot"); index += 1) {
    const next = page.getByRole("button", { name: "Next item ]" });
    await expect(next).toBeEnabled();
    await next.click();
    correctionOptions = await correctionSelect.locator("option").allTextContents();
  }
  expect(correctionOptions).toContain("Change primary shot");
  await correctionSelect.selectOption("change_shot_type");
  const primaryShot = page.locator(".correction-editor select").nth(1);
  const editorShotType = await primaryShot.inputValue();
  const correctedShotType = editorShotType === "drop" ? "boast" : "drop";
  await primaryShot.selectOption(correctedShotType);
  expect(await primaryShot.inputValue()).not.toBe(editorShotType);
  await page.getByLabel("Reason").fill("Verified from the published video evidence");
  const correctionRequestPromise = page.waitForRequest((request) => (
    request.url().endsWith(`/matches/${matchId}/corrections`)
    && request.method() === "POST"
  ));
  await page.getByRole("button", { name: "Save correction" }).click();
  const correctionRequest = await correctionRequestPromise;
  const correctionBody = objectValue(correctionRequest.postDataJSON());
  if (typeof correctionBody.targetId !== "string") {
    throw new TypeError("correction target id is invalid");
  }
  const priorEvidenceResponse = await page.request.get(
    `/api/v1/matches/${encodeURIComponent(matchId)}/evidence/${encodeURIComponent(correctionBody.targetId)}?revision=${initialRevision}`,
  );
  expect(priorEvidenceResponse.ok()).toBe(true);
  const priorEvidence = objectValue(await priorEvidenceResponse.json());
  const priorSummary = objectValue(priorEvidence.summary);
  const priorShotType = (
    typeof priorSummary.shotKind === "string"
      ? priorSummary.shotKind
      : typeof priorSummary.shotType === "string"
        ? priorSummary.shotType
        : priorSummary.shot_type
  );
  if (typeof priorShotType !== "string") {
    throw new TypeError("prior canonical shot type is invalid");
  }
  expect(correctedShotType).not.toBe(priorShotType);
  const priorCountBefore = shotTypeCount(beforeReport, priorShotType);
  const correctedCountBefore = shotTypeCount(
    beforeReport,
    correctedShotType,
  );
  await expect.poll(
    async () => Number(await revisionSelect.inputValue()),
  ).toBeGreaterThan(initialRevision);
  const correctedRevision = Number(await revisionSelect.inputValue());
  const afterReportResponse = await page.request.get(
    `/api/v1/matches/${encodeURIComponent(matchId)}/reports/${correctedRevision}`,
  );
  expect(afterReportResponse.ok()).toBe(true);
  const afterReport = objectValue(await afterReportResponse.json());
  const afterSections = objectValue(afterReport.sections);
  const afterShots = objectValue(afterSections.shots);
  expect(afterShots.hash).not.toBe(beforeShots.hash);
  expect(JSON.stringify(afterShots.payload)).not.toBe(beforeShotPayload);
  const priorCountAfter = shotTypeCount(afterReport, priorShotType);
  const correctedCountAfter = shotTypeCount(
    afterReport,
    correctedShotType,
  );
  expect(priorCountAfter).toBe(priorCountBefore - 1);
  expect(correctedCountAfter).toBe(correctedCountBefore + 1);
  await expect(page.getByText(/reviewed/).first()).toBeVisible();

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("Report revision")).toHaveValue(String(correctedRevision));
  await expect(page).toHaveURL(new RegExp(`revision=${correctedRevision}`));
  const persistedReportResponse = await page.request.get(
    `/api/v1/matches/${encodeURIComponent(matchId)}/reports/${correctedRevision}`,
  );
  expect(persistedReportResponse.ok()).toBe(true);
  const persistedReport = objectValue(
    await persistedReportResponse.json(),
  );
  expect(shotTypeCount(persistedReport, priorShotType)).toBe(
    priorCountAfter,
  );
  expect(shotTypeCount(persistedReport, correctedShotType)).toBe(
    correctedCountAfter,
  );

  await page.getByText("Export options", { exact: true }).click();
  const evidenceClips = page.getByRole("checkbox", { name: "Include evidence clips" });
  await expect(evidenceClips).toBeEnabled();
  await evidenceClips.check();
  await page.getByRole("button", { name: "Build local export" }).click();
  const downloadLink = page.getByRole("link", { name: "Download completed export" });
  await expect(downloadLink).toBeVisible({ timeout: 5 * 60 * 1000 });
  const downloadPromise = page.waitForEvent("download");
  await downloadLink.click();
  const download = await downloadPromise;
  const archivePath = await download.path();
  if (archivePath === null) throw new Error("completed export download has no local file");
  const extraction = mkdtempSync(resolve(tmpdir(), "squashvision-export-"));
  execFileSync(PYTHON, ["-m", "zipfile", "-e", archivePath, extraction], { stdio: "pipe" });
  const manifest = objectValue(JSON.parse(readFileSync(resolve(extraction, "manifest.json"), "utf8")));
  const reportDocument = objectValue(JSON.parse(readFileSync(resolve(extraction, "report.json"), "utf8")));
  const reportRecord = objectValue(reportDocument.report);
  const rawMembers = manifest.members;
  if (!Array.isArray(rawMembers)) throw new TypeError("export manifest members are invalid");
  const memberNames = rawMembers.map((member) => {
    const record = objectValue(member);
    if (typeof record.name !== "string") throw new TypeError("export manifest member name is invalid");
    return record.name;
  });
  expect(manifest.createdRevision).toBe(correctedRevision);
  expect(reportRecord.revision).toBe(correctedRevision);
  expect(memberNames).toEqual(expect.arrayContaining([
    "report.html",
    "report.json",
    "data/canonical_shots.csv",
  ]));
  const clipName = memberNames.find((name) => /^evidence\/clip-\d{3}\.mp4$/.test(name));
  expect(clipName).toBeDefined();
  expect(statSync(resolve(extraction, String(clipName))).size).toBeGreaterThan(0);
  rmSync(extraction, { recursive: true, force: true });
  await page.screenshot({ path: testInfo.outputPath("04-export-complete.png"), fullPage: true });

  await page.getByRole("link", { name: "Matches", exact: true }).click();
  const row = page.getByRole("listitem", { name: /Task 16 recovery match/ });
  await expect(row).toBeVisible();
  await row.getByText("More options").click();
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Match deleted")).toBeVisible();
  await expect(row).toHaveCount(0);
});
});
