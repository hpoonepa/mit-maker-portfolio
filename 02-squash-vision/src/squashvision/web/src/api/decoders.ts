import type { components } from "./types.generated";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type MatchDetail = components["schemas"]["MatchDetail"];
export type MatchListPage = components["schemas"]["MatchListPage"];
export type MatchSummary = components["schemas"]["MatchSummary"];
export type ModelAssetDetail = components["schemas"]["ModelAssetDetail"];
export type CalibrationDetail = components["schemas"]["CalibrationDetail"];
export type CalibrationProposal = components["schemas"]["CalibrationProposalDetail"];
export type CalibrationKeypoint = components["schemas"]["CalibrationKeypoint"];
export type CalibrationSize = components["schemas"]["CalibrationSize"];
export type JobDetail = components["schemas"]["JobDetail"];
export type JobEvent = components["schemas"]["JobEvent"];
export type ProcessingProfile = components["schemas"]["ProcessingProfile"];
export type MatchReport = components["schemas"]["MatchReport"];
export type ReportListPage = components["schemas"]["ReportListPage"];
export type TimelinePage = components["schemas"]["TimelinePage"];
export type TimelineItem = components["schemas"]["TimelineItem"];
export type PlayerObservationPage = components["schemas"]["PlayerObservationPage"];
export type BallObservationPage = components["schemas"]["BallObservationPage"];
export type CorrectionConflictList = components["schemas"]["CorrectionConflictList"];
export type ReviewItemPage = components["schemas"]["ReviewItemPage"];
export type ExportDetail = components["schemas"]["ExportDetail"];
export type ShotDetail = components["schemas"]["ShotDetail"];
export type ShotPage = components["schemas"]["ShotPage"];

type ShotKind = components["schemas"]["ShotKind"];
type ShotOutcomeKind = components["schemas"]["ShotOutcomeKind"];


const JOB_STATES: Record<string, true> = {
  queued: true,
  running: true,
  paused: true,
  completed: true,
  failed: true,
  cancelled: true,
};
const PROCESSING_STATES: Record<string, true> = { ...JOB_STATES, not_started: true };
const PROFILES: Record<string, true> = { fast: true, balanced: true, maximum: true };
const STAGES: Record<string, true> = {
  prepare: true,
  calibration: true,
  players: true,
  ball: true,
  events: true,
  classification: true,
  report: true,
};
const STAGE_STATES: Record<string, true> = {
  pending: true,
  running: true,
  completed: true,
  failed: true,
  invalidated: true,
};
const MODEL_STATES: Record<string, true> = {
  missing: true,
  downloading: true,
  ready: true,
  corrupt: true,
  incompatible: true,
};
const SHOT_KINDS: Record<ShotKind, true> = {
  unknown: true,
  serve: true,
  drive: true,
  drop: true,
  boast: true,
  lob: true,
  kill: true,
};
const SHOT_OUTCOMES: Record<ShotOutcomeKind, true> = {
  unknown: true,
  in_play: true,
  winner: true,
  error: true,
  stroke: true,
  let: true,
};

function decodeShotDetailValue(value: unknown): ShotDetail {
  const shot = record(value);
  stringField(shot, "id");
  const timestampUs = numberField(shot, "timestampUs");
  if (!Number.isSafeInteger(timestampUs) || timestampUs < 0) throw new TypeError("timestampUs must be a nonnegative integer");
  const predictionRevision = numberField(shot, "predictionRevision");
  if (!Number.isSafeInteger(predictionRevision) || predictionRevision < 1) throw new TypeError("predictionRevision must be a positive integer");
  nullableString(shot, "rallyId");
  nullableEnum(shot, "hitter", { near: true, far: true });
  enumField(shot, "shotKind", SHOT_KINDS);
  booleanField(shot, "isVolley");
  enumField(shot, "outcome", SHOT_OUTCOMES);
  const contact = required(shot, "contact");
  if (contact !== null) numberTuple(shot, "contact", 2);
  nullableNumber(shot, "speedMS");
  nullableString(shot, "speedUnavailableReason");
  stringArray(shot, "sourceEvidenceIds");
  return value as ShotDetail;
}

export function decodeShotDetail(value: unknown): ShotDetail {
  return decodeShotDetailValue(value);
}

export function decodeShotPage(value: unknown): ShotPage {
  const page = record(value);
  nullableString(page, "nextCursor");
  const revision = numberField(page, "predictionRevision");
  if (!Number.isSafeInteger(revision) || revision < 1) throw new TypeError("predictionRevision must be a positive integer");
  for (const candidate of arrayField(page, "items")) decodeShotDetailValue(candidate);
  return value as ShotPage;
}
function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("expected an object");
  }
  return value as Record<string, unknown>;
}

function required(value: Record<string, unknown>, name: string): unknown {
  if (!(name in value)) throw new TypeError(`${name} is required`);
  return value[name];
}

function stringField(value: Record<string, unknown>, name: string): string {
  const field = required(value, name);
  if (typeof field !== "string") throw new TypeError(`${name} must be a string`);
  return field;
}

function numberField(value: Record<string, unknown>, name: string): number {
  const field = required(value, name);
  if (typeof field !== "number" || !Number.isFinite(field)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return field;
}

function booleanField(value: Record<string, unknown>, name: string): boolean {
  const field = required(value, name);
  if (typeof field !== "boolean") throw new TypeError(`${name} must be a boolean`);
  return field;
}

function nullableString(value: Record<string, unknown>, name: string): string | null {
  const field = required(value, name);
  if (field !== null && typeof field !== "string") {
    throw new TypeError(`${name} must be a string or null`);
  }
  return field;
}

function nullableNumber(value: Record<string, unknown>, name: string): number | null {
  const field = required(value, name);
  if (field !== null && (typeof field !== "number" || !Number.isFinite(field))) {
    throw new TypeError(`${name} must be a finite number or null`);
  }
  return field;
}

function nullableFiniteMatrix(
  value: Record<string, unknown>,
  name: string,
  size: number,
): number[][] | null {
  const field = required(value, name);
  if (field === null) return null;
  if (!Array.isArray(field) || field.length !== size) {
    const article = size === 8 ? "an" : "a";
    throw new TypeError(`${name} must be ${article} ${size}x${size} matrix or null`);
  }
  for (const row of field) {
    if (!Array.isArray(row) || row.length !== size) {
      const article = size === 8 ? "an" : "a";
      throw new TypeError(`${name} must be ${article} ${size}x${size} matrix or null`);
    }
    for (const entry of row) {
      if (typeof entry !== "number" || !Number.isFinite(entry)) {
        throw new TypeError(`${name} entries must be finite numbers`);
      }
    }
  }
  return field as number[][];
}

function optionalNullableString(value: Record<string, unknown>, name: string): void {
  if (name in value && value[name] !== null && typeof value[name] !== "string") {
    throw new TypeError(`${name} must be a string or null when present`);
  }
}
function optionalNullableNumber(value: Record<string, unknown>, name: string): void {
  if (
    name in value
    && value[name] !== null
    && (typeof value[name] !== "number" || !Number.isFinite(value[name]))
  ) {
    throw new TypeError(`${name} must be a finite number or null when present`);
  }
}

function numberTuple(value: Record<string, unknown>, name: string, length: number): void {
  const tuple = arrayField(value, name);
  if (tuple.length !== length || !tuple.every((entry) => typeof entry === "number" && Number.isFinite(entry))) {
    throw new TypeError(`${name} must contain ${length} finite numbers`);
  }
}


function arrayField(value: Record<string, unknown>, name: string): unknown[] {
  const field = required(value, name);
  if (!Array.isArray(field)) throw new TypeError(`${name} must be an array`);
  return field;
}

function stringArray(value: Record<string, unknown>, name: string): string[] {
  const fields = arrayField(value, name);
  if (!fields.every((field) => typeof field === "string")) {
    throw new TypeError(`${name} entries must be strings`);
  }
  return fields;
}

function enumField(value: Record<string, unknown>, name: string, allowed: Record<string, true>): string {
  const field = stringField(value, name);
  if (!(field in allowed)) throw new TypeError(`${name} has an unknown value`);
  return field;
}

function nullableEnum(value: Record<string, unknown>, name: string, allowed: Record<string, true>): void {
  const field = required(value, name);
  if (field !== null && (typeof field !== "string" || !(field in allowed))) {
    throw new TypeError(`${name} has an unknown value`);
  }
}

function decodeKeypoint(value: unknown): void {
  const point = record(value);
  stringField(point, "label");
  const image = record(required(point, "image"));
  numberField(image, "x");
  numberField(image, "y");
  const court = record(required(point, "court"));
  numberField(court, "xM");
  numberField(court, "yM");
}

function decodeReport(value: unknown): void {
  const report = record(value);
  numberField(report, "revision");
  numberField(report, "predictionRevision");
  nullableNumber(report, "calibrationRevision");
  stringField(report, "createdAt");
  const hashes = record(required(report, "sectionHashes"));
  if (!Object.values(hashes).every((hash) => typeof hash === "string")) {
    throw new TypeError("sectionHashes values must be strings");
  }
}

function decodeJobValue(value: unknown): JobDetail {
  const item = record(value);
  stringField(item, "id");
  stringField(item, "matchId");
  enumField(item, "profile", PROFILES);
  enumField(item, "state", JOB_STATES);
  nullableEnum(item, "stage", STAGES);
  nullableEnum(item, "stageState", STAGE_STATES);
  nullableEnum(item, "requestedState", JOB_STATES);
  numberField(item, "version");
  stringField(item, "createdAt");
  stringField(item, "updatedAt");
  nullableString(item, "heartbeatAt");
  nullableNumber(item, "currentRangeStartUs");
  nullableNumber(item, "currentRangeEndUs");
  nullableString(item, "failureCode");
  const start = item.currentRangeStartUs;
  const end = item.currentRangeEndUs;
  if ((start === null) !== (end === null) || (typeof start === "number" && typeof end === "number" && start >= end)) {
    throw new TypeError("current range endpoints are inconsistent");
  }
  const progressValue = required(item, "progress");
  if (progressValue !== null) {
    const progress = record(progressValue);
    numberField(progress, "completedChunks");
    numberField(progress, "plannedChunks");
    numberField(progress, "fraction");
  }
  return value as JobDetail;
}

export function decodeHealth(value: unknown): HealthResponse {
  const health = record(value);
  enumField(health, "status", { ready: true, degraded: true });
  stringField(health, "version");
  const ffmpeg = record(required(health, "ffmpeg"));
  enumField(ffmpeg, "status", { ready: true, unavailable: true });
  const worker = record(required(health, "worker"));
  enumField(worker, "status", { ready: true, unavailable: true });
  stringField(worker, "architecture");
  booleanField(worker, "nativeAppleSilicon");
  booleanField(worker, "mpsAvailable");
  const models = record(required(health, "models"));
  stringField(models, "status");
  for (const candidate of arrayField(models, "assets")) {
    const asset = record(candidate);
    stringField(asset, "name");
    booleanField(asset, "required");
    enumField(asset, "state", MODEL_STATES);
    nullableString(asset, "errorCode");
  }
  return value as HealthResponse;
}

export function decodeModels(value: unknown): ModelAssetDetail[] {
  if (!Array.isArray(value)) throw new TypeError("models must be an array");
  for (const candidate of value) {
    const model = record(candidate);
    for (const name of ["name", "filename", "requestedRevision", "sourceLabel", "declaredLicense"]) {
      stringField(model, name);
    }
    nullableString(model, "resolvedRevision");
    nullableNumber(model, "byteSize");
    nullableString(model, "sha256");
    nullableString(model, "downloadedAt");
    nullableString(model, "errorCode");
    numberField(model, "compatibilityVersion");
    booleanField(model, "required");
    enumField(model, "state", MODEL_STATES);
  }
  return value as ModelAssetDetail[];
}

export function decodeMatchPage(value: unknown): MatchListPage {
  const page = record(value);
  for (const candidate of arrayField(page, "items")) decodeMatchSummary(candidate);
  nullableString(page, "nextCursor");
  return value as MatchListPage;
}

export function decodeMatchSummary(value: unknown): MatchSummary {
  const match = record(value);
  stringField(match, "id");
  stringField(match, "title");
  stringField(match, "updatedAt");
  enumField(match, "preparationState", { prepared: true, unprepared: true });
  numberField(match, "version");
  const metadata = record(required(match, "metadata"));
  for (const name of ["playerOne", "playerTwo", "playedOn", "score"]) optionalNullableString(metadata, name);
  const processing = record(required(match, "processing"));
  enumField(processing, "state", PROCESSING_STATES);
  for (const name of ["jobId", "updatedAt"]) optionalNullableString(processing, name);
  if ("profile" in processing && processing.profile !== null) enumField(processing, "profile", PROFILES);
  if ("stage" in processing && processing.stage !== null) enumField(processing, "stage", STAGES);
  const latestReport = required(match, "latestReport");
  if (latestReport !== null) decodeReport(latestReport);
  const quality = record(required(match, "quality"));
  stringField(quality, "availability");
  stringArray(quality, "warnings");
  return value as MatchSummary;
}

export function decodeMatchDetail(value: unknown): MatchDetail {
  const match = record(value);
  decodeMatchSummary({
    ...match,
    processing: match.latestJob === null || match.latestJob === undefined
      ? { state: "not_started" }
      : {
          state: record(match.latestJob).state,
          jobId: record(match.latestJob).id,
          profile: record(match.latestJob).profile,
          stage: record(match.latestJob).stage,
          updatedAt: record(match.latestJob).updatedAt,
        },
  });
  for (const candidate of arrayField(match, "assets")) {
    const asset = record(candidate);
    stringField(asset, "id");
    enumField(asset, "kind", { original: true, proxy: true, frame: true, timestamp_map: true, export: true, model: true });
    optionalNullableString(asset, "timestampIndexPath");
    if ("byteSize" in asset) nullableNumber(asset, "byteSize");
    if ("durationUs" in asset) nullableNumber(asset, "durationUs");
    booleanField(asset, "timestampIndexAvailable");
  }
  const latestJob = required(match, "latestJob");
  if (latestJob !== null) decodeJobValue(latestJob);
  const modelQuality = required(match, "modelQuality");
  decodeModels(modelQuality);
  return value as MatchDetail;
}

export function decodeCalibration(value: unknown): CalibrationDetail {
  const calibration = record(value);
  numberField(calibration, "revision");
  stringField(calibration, "proxyId");
  const frameSize = required(calibration, "frameSize");
  if (frameSize !== null) {
    const size = record(frameSize);
    if (numberField(size, "width") <= 0 || numberField(size, "height") <= 0) {
      throw new TypeError("frameSize dimensions must be positive");
    }
  }
  for (const candidate of arrayField(calibration, "keypoints")) decodeKeypoint(candidate);
  const result = record(required(calibration, "result"));
  booleanField(result, "calibrated");
  numberField(result, "confidence");
  for (const name of ["rmsErrorPx", "maxErrorPx", "conditionNumber"]) nullableNumber(result, name);
  nullableFiniteMatrix(result, "imageToCourt", 3);
  nullableFiniteMatrix(result, "courtToImage", 3);
  nullableFiniteMatrix(result, "parameterCovariance", 8);
  stringArray(result, "warnings");
  arrayField(result, "residualsPx").forEach((entry) => {
    if (typeof entry !== "number" || !Number.isFinite(entry)) throw new TypeError("residualsPx entries must be finite numbers");
  });
  arrayField(result, "inlierMask").forEach((entry) => {
    if (typeof entry !== "boolean") throw new TypeError("inlierMask entries must be booleans");
  });
  const capabilities = record(required(result, "capabilities"));
  for (const name of ["imageSpace", "floorPosition", "movementDistance", "speed"]) booleanField(capabilities, name);
  return value as CalibrationDetail;
}

export function decodeProposal(value: unknown): CalibrationProposal {
  const proposal = record(value);
  numberField(proposal, "confidence");
  numberField(proposal, "intersectionCount");
  numberField(proposal, "lineCount");
  stringArray(proposal, "visibleSurfaces");
  stringArray(proposal, "warnings");
  for (const candidate of arrayField(proposal, "keypoints")) decodeKeypoint(candidate);
  return value as CalibrationProposal;
}

export function decodeJob(value: unknown): JobDetail {
  return decodeJobValue(value);
}

export function decodeJobEvent(value: unknown): JobEvent {
  const event = record(value);
  numberField(event, "eventVersion");
  decodeJobValue(required(event, "job"));
  return value as JobEvent;
}

function decodeArtifact(value: unknown): void {
  const artifact = record(value);
  stringField(artifact, "availability");
  stringField(artifact, "jobId");
  stringArray(artifact, "modelManifestIds");
  stringArray(artifact, "sourceManifestIds");
  enumField(artifact, "stage", STAGES);
  stringArray(artifact, "warnings");
}

function decodeObservationPage(value: unknown): Record<string, unknown> {
  const page = record(value);
  decodeArtifact(required(page, "artifact"));
  const startUs = numberField(page, "startUs");
  const endUs = numberField(page, "endUs");
  if (startUs >= endUs) throw new TypeError("observation page range must be positive");
  nullableString(page, "nextCursor");
  return page;
}

export function decodeMatchReport(value: unknown): MatchReport {
  const report = record(value);
  stringField(report, "matchId");
  numberField(report, "revision");
  numberField(report, "predictionRevision");
  nullableNumber(report, "calibrationRevision");
  const sections = record(required(report, "sections"));
  for (const [name, candidate] of Object.entries(sections)) {
    const section = record(candidate);
    numberField(section, "schemaVersion");
    record(required(section, "payload"));
    stringArray(section, "evidenceIds");
    stringField(section, "hash");
    stringField(section, "dependencyHash");
    if (name.length === 0) throw new TypeError("report section names cannot be empty");
  }
  return value as MatchReport;
}

export function decodeReportList(value: unknown): ReportListPage {
  const page = record(value);
  for (const candidate of arrayField(page, "items")) decodeReport(candidate);
  nullableString(page, "nextCursor");
  return value as ReportListPage;
}

export function decodeTimelineItem(value: unknown): TimelineItem {
  const item = record(value);
  if ("id" in item) nullableString(item, "id");
  stringField(item, "kind");
  numberField(item, "timestampUs");
  optionalNullableNumber(item, "endUs");
  if ("evidenceIds" in item) stringArray(item, "evidenceIds");
  if ("summary" in item) record(item.summary);
  if ("observationLinks" in item && item.observationLinks !== null) {
    const links = record(item.observationLinks);
    if (!Object.values(links).every((link) => typeof link === "string")) {
      throw new TypeError("observationLinks values must be strings");
    }
  }
  return value as TimelineItem;
}


export function decodeTimelinePage(value: unknown): TimelinePage {
  const page = record(value);
  numberField(page, "predictionRevision");
  nullableString(page, "nextCursor");
  for (const candidate of arrayField(page, "items")) decodeTimelineItem(candidate);
  return value as TimelinePage;
}

export function decodePlayerObservationPage(value: unknown): PlayerObservationPage {
  const page = decodeObservationPage(value);
  for (const candidate of arrayField(page, "items")) {
    const item = record(candidate);
    nullableString(item, "ambiguityReason");
    booleanField(item, "ambiguous");
    numberField(item, "associationConfidence");
    numberTuple(item, "box", 4);
    nullableString(item, "calibrationProvenance");
    nullableString(item, "calibrationRevision");
    numberField(item, "detectionConfidence");
    stringField(item, "evidence");
    numberField(item, "evidenceEndFrameIndex");
    numberField(item, "evidenceEndTimestampUs");
    numberField(item, "evidenceStartFrameIndex");
    numberField(item, "evidenceStartTimestampUs");
    numberTuple(item, "feet", 2);
    for (const keypoint of arrayField(item, "keypoints")) {
      const point = record(keypoint);
      numberField(point, "x");
      numberField(point, "y");
      numberField(point, "confidence");
    }
    for (const edge of arrayField(item, "skeletonEdges")) {
      if (!Array.isArray(edge) || edge.length !== 2 || !edge.every((value) => typeof value === "number" && Number.isInteger(value))) {
        throw new TypeError("skeletonEdges entries must be integer pairs");
      }
    }
    numberField(item, "feetUncertaintyPx");
    const floor = required(item, "floor");
    if (floor !== null) numberTuple(item, "floor", 2);
    optionalNullableNumber(item, "floorUncertaintyM");
    stringField(item, "modelManifestId");
    stringField(item, "playerId");
    optionalNullableNumber(item, "sourceFrameIndex");
    stringField(item, "sourceManifestId");
    optionalNullableNumber(item, "sourceTimestampUs");
    numberField(item, "timestampUs");
  }
  return value as PlayerObservationPage;
}

export function decodeBallObservationPage(value: unknown): BallObservationPage {
  const page = decodeObservationPage(value);
  for (const candidate of arrayField(page, "items")) {
    const item = record(candidate);
    nullableString(item, "ambiguityReason");
    booleanField(item, "ambiguous");
    numberField(item, "candidateCount");
    stringField(item, "device");
    booleanField(item, "deviceFallback");
    stringField(item, "evidence");
    numberField(item, "evidenceEndFrameIndex");
    numberField(item, "evidenceEndTimestampUs");
    numberField(item, "evidenceStartFrameIndex");
    numberField(item, "evidenceStartTimestampUs");
    stringField(item, "modelManifestId");
    numberField(item, "probability");
    const covariance = required(item, "covariance");
    if (covariance !== null) {
      if (!Array.isArray(covariance) || covariance.length !== 2) throw new TypeError("covariance must be a 2x2 matrix");
      for (const row of covariance) {
        if (!Array.isArray(row) || row.length !== 2 || !row.every((entry) => typeof entry === "number" && Number.isFinite(entry))) throw new TypeError("covariance must contain finite values");
      }
    }
    for (const candidateDetail of arrayField(item, "candidates")) {
      const detail = record(candidateDetail);
      numberField(detail, "x");
      numberField(detail, "y");
      numberField(detail, "probability");
      const matrix = arrayField(detail, "covariance");
      if (matrix.length !== 2 || matrix.some((row) => !Array.isArray(row) || row.length !== 2 || !row.every((entry) => typeof entry === "number" && Number.isFinite(entry)))) throw new TypeError("candidate covariance must be a 2x2 finite matrix");
    }
    nullableString(item, "segmentId");
    optionalNullableNumber(item, "sourceFrameIndex");
    numberField(item, "sourceHeight");
    stringField(item, "sourceManifestId");
    optionalNullableNumber(item, "sourceTimestampUs");
    numberField(item, "sourceWidth");
    numberField(item, "timestampUs");
    booleanField(item, "visible");
    nullableNumber(item, "x");
    nullableNumber(item, "y");
  }
  return value as BallObservationPage;
}

export function decodeCorrectionConflicts(value: unknown): CorrectionConflictList {
  const list = record(value);
  for (const candidate of arrayField(list, "conflicts")) {
    const conflict = record(candidate);
    stringField(conflict, "correctionId");
    stringField(conflict, "reason");
    stringArray(conflict, "candidateIds");
    for (const detailCandidate of arrayField(conflict, "candidates")) {
      const detail = record(detailCandidate);
      stringField(detail, "candidateId");
      numberField(detail, "timestampUs");
      numberField(detail, "evidenceStartTimestampUs");
      numberField(detail, "evidenceEndTimestampUs");
      optionalNullableNumber(detail, "evidenceStartFrameIndex");
      optionalNullableNumber(detail, "evidenceEndFrameIndex");
      stringArray(detail, "evidenceIds");
      stringField(detail, "label");
    }
  }
  return value as CorrectionConflictList;
}

export function decodeReviewItemPage(value: unknown): ReviewItemPage {
  const page = record(value);
  numberField(page, "reportRevision");
  nullableString(page, "nextCursor");
  for (const candidate of arrayField(page, "items")) {
    const item = record(candidate);
    stringField(item, "id");
    stringField(item, "targetType");
    stringField(item, "kind");
    numberField(item, "timestampUs");
    optionalNullableNumber(item, "endUs");
    optionalNullableNumber(item, "confidence");
    stringField(item, "issue");
    stringField(item, "provenance");
    const probabilities = record(required(item, "probabilities"));
    if (!Object.values(probabilities).every((entry) => typeof entry === "number" && Number.isFinite(entry))) throw new TypeError("review probabilities must be finite numbers");
    stringArray(item, "reasons");
    stringArray(item, "evidenceIds");
    numberField(item, "evidenceStartTimestampUs");
    numberField(item, "evidenceEndTimestampUs");
    optionalNullableNumber(item, "evidenceStartFrameIndex");
    optionalNullableNumber(item, "evidenceEndFrameIndex");
    stringArray(item, "invalidatedSections");
    stringArray(item, "invalidatedStats");
    record(required(item, "summary"));
    const reviewEntityType = stringField(item, "reviewEntityType");
    if (reviewEntityType !== "error_candidate" && reviewEntityType !== "shot" && reviewEntityType !== "rally") {
      throw new TypeError("reviewEntityType must be error_candidate, shot, or rally");
    }
    stringField(item, "reviewEntityId");
    stringField(item, "reviewStatus");
    const targets = record(required(item, "commandTargets"));
    for (const candidateTarget of Object.values(targets)) {
      const target = record(candidateTarget);
      stringField(target, "targetType");
      stringField(target, "targetId");
      numberField(target, "sourceTimestampUs");
      stringArray(target, "sourceEvidenceIds");
      numberField(target, "evidenceStartTimestampUs");
      numberField(target, "evidenceEndTimestampUs");
      optionalNullableNumber(target, "evidenceStartFrameIndex");
      optionalNullableNumber(target, "evidenceEndFrameIndex");
    }
    const impacts = record(required(item, "commandImpacts"));
    for (const candidateImpact of Object.values(impacts)) {
      const impact = record(candidateImpact);
      stringArray(impact, "invalidatedSections");
      stringArray(impact, "invalidatedStats");
    }
  }
  return value as ReviewItemPage;
}

export function decodeExportDetail(value: unknown): ExportDetail {
  const detail = record(value);
  stringField(detail, "id");
  stringField(detail, "matchId");
  const revision = numberField(detail, "revision");
  if (!Number.isSafeInteger(revision) || revision < 1) throw new TypeError("revision must be a positive integer");
  if (stringField(detail, "state") !== "completed") throw new TypeError("export state must be completed");
  const selection = record(required(detail, "selection"));
  const formats = stringArray(selection, "formats");
  if (formats.length < 1 || !formats.every((format) => format === "html" || format === "json" || format === "csv")) {
    throw new TypeError("export formats are invalid");
  }
  stringArray(selection, "evidenceIds");
  numberField(selection, "evidenceDurationSeconds");
  booleanField(selection, "includeOriginal");
  stringField(detail, "relativePath");
  const byteSize = numberField(detail, "byteSize");
  if (!Number.isSafeInteger(byteSize) || byteSize < 0) throw new TypeError("byteSize must be a nonnegative integer");
  const sha256 = stringField(detail, "sha256");
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new TypeError("sha256 is invalid");
  return value as ExportDetail;
}
