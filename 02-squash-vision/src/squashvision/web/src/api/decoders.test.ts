import { describe, expect, it } from "vitest";

import {
  decodeCalibration,
  decodeExportDetail,
  decodeMatchPage,
  decodeModels,
  decodeProposal,
  decodeShotDetail,
  decodeShotPage,
} from "./decoders";

const validSummary = {
  id: "match-1",
  title: "Final",
  metadata: { playerOne: "A", playerTwo: null, playedOn: "2026-08-25", score: null },
  preparationState: "prepared",
  updatedAt: "2026-08-25T12:00:00Z",
  version: 1,
  processing: { state: "running", jobId: "job-1", profile: "balanced", stage: "players", updatedAt: "2026-08-25T12:00:00Z" },
  latestReport: {
    revision: 1,
    predictionRevision: 1,
    calibrationRevision: null,
    createdAt: "2026-08-25T12:00:00Z",
    sectionHashes: { overview: "a".repeat(64) },
  },
  quality: { availability: "partial", warnings: [] },
};

const validPoint = {
  label: "front-left",
  image: { x: 20, y: 30 },
  court: { xM: 0, yM: 0 },
};

describe("generated response decoders", () => {
  it("recursively validates match metadata, processing, quality, and report fields", () => {
    expect(decodeMatchPage({ items: [validSummary], nextCursor: null }).items).toHaveLength(1);
    expect(() => decodeMatchPage({
      items: [{ ...validSummary, processing: { ...validSummary.processing, state: "mystery" } }],
      nextCursor: null,
    })).toThrow();
    expect(() => decodeMatchPage({
      items: [{ ...validSummary, metadata: { ...validSummary.metadata, playerOne: 42 } }],
      nextCursor: null,
    })).toThrow();
    expect(() => decodeMatchPage({
      items: [{ ...validSummary, latestReport: { ...validSummary.latestReport, revision: null } }],
      nextCursor: null,
    })).toThrow();
  });

  it("accepts a null calibration frame size but validates every proposal point and count", () => {
    const detail = decodeCalibration({
      revision: 1,
      proxyId: "proxy-1",
      frameSize: null,
      keypoints: [validPoint],
      result: {
        calibrated: false,
        imageToCourt: null,
        courtToImage: null,
        residualsPx: [],
        rmsErrorPx: null,
        maxErrorPx: null,
        inlierMask: [],
        conditionNumber: null,
        parameterCovariance: null,
        confidence: 0,
        capabilities: { imageSpace: true, floorPosition: false, movementDistance: false, speed: false },
        warnings: [],
      },
    });
    expect(detail.frameSize).toBeNull();

    expect(decodeProposal({
      keypoints: [validPoint],
      confidence: 0.8,
      visibleSurfaces: ["floor"],
      warnings: [],
      lineCount: 4,
      intersectionCount: 4,
    }).intersectionCount).toBe(4);
    expect(() => decodeProposal({
      keypoints: [{ ...validPoint, court: { xM: "left", yM: 0 } }],
      confidence: 0.8,
      visibleSurfaces: ["floor"],
      warnings: [],
      lineCount: 4,
      intersectionCount: 4,
    })).toThrow();
    expect(() => decodeProposal({
      keypoints: [validPoint],
      confidence: 0.8,
      visibleSurfaces: [3],
      warnings: [],
      lineCount: null,
      intersectionCount: 4,
    })).toThrow();
  });

  it("requires finite 3x3 homographies and a finite 8x8 parameter covariance", () => {
    const homography = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    const covariance = Array.from({ length: 8 }, (_, row) =>
      Array.from({ length: 8 }, (_, column) => row === column ? 1 : 0));
    const calibration = {
      revision: 2,
      proxyId: "proxy-1",
      frameSize: { width: 1280, height: 720 },
      keypoints: [validPoint],
      result: {
        calibrated: true,
        imageToCourt: homography,
        courtToImage: homography,
        residualsPx: [1],
        rmsErrorPx: 1,
        maxErrorPx: 1,
        inlierMask: [true],
        conditionNumber: 1,
        parameterCovariance: covariance,
        confidence: 0.9,
        capabilities: { imageSpace: true, floorPosition: true, movementDistance: true, speed: true },
        warnings: [],
      },
    };
    expect(decodeCalibration(calibration).result.imageToCourt).toEqual(homography);

    const { imageToCourt: _imageToCourt, ...missingHomography } = calibration.result;
    expect(() => decodeCalibration({
      ...calibration,
      result: missingHomography,
    })).toThrow(/imageToCourt is required/);
    expect(() => decodeCalibration({
      ...calibration,
      result: { ...calibration.result, courtToImage: [[1, 0, 0], [0, 1, 0]] },
    })).toThrow(/courtToImage must be a 3x3 matrix/);
    expect(() => decodeCalibration({
      ...calibration,
      result: { ...calibration.result, imageToCourt: [[1, 0, 0], [0, Number.POSITIVE_INFINITY, 0], [0, 0, 1]] },
    })).toThrow(/imageToCourt entries must be finite numbers/);
    expect(() => decodeCalibration({
      ...calibration,
      result: { ...calibration.result, parameterCovariance: covariance.slice(0, 7) },
    })).toThrow(/parameterCovariance must be an 8x8 matrix/);
    expect(() => decodeCalibration({
      ...calibration,
      result: { ...calibration.result, parameterCovariance: covariance.map((row, index) => index === 3 ? [...row.slice(0, 7), Number.NaN] : row) },
    })).toThrow(/parameterCovariance entries must be finite numbers/);
  });

  it("validates exact model states and every nullable provenance field", () => {
    const model = {
      name: "ball",
      filename: "ball.pt",
      requestedRevision: "main",
      resolvedRevision: null,
      byteSize: null,
      sha256: null,
      declaredLicense: "not-declared",
      downloadedAt: null,
      compatibilityVersion: 1,
      required: true,
      state: "missing",
      errorCode: null,
      sourceLabel: "Hugging Face · owner/repo",
    };
    expect(decodeModels([model])).toHaveLength(1);
    expect(() => decodeModels([{ ...model, state: "waiting" }])).toThrow();
    expect(() => decodeModels([{ ...model, byteSize: Number.NaN }])).toThrow();
    expect(() => decodeModels([{ ...model, resolvedRevision: 42 }])).toThrow();
    expect(() => decodeModels([{ ...model, sourceLabel: null }])).toThrow();
  });

  it("accepts only completed revision-pinned export bundles with verified metadata", () => {
    const detail = {
      id: "export-1",
      matchId: "match-1",
      revision: 4,
      state: "completed",
      selection: {
        formats: ["html", "json", "csv"],
        evidenceIds: ["evidence-1"],
        evidenceDurationSeconds: 6,
        includeOriginal: false,
      },
      relativePath: "exports/export-1.zip",
      byteSize: 2048,
      sha256: "a".repeat(64),
    };
    expect(decodeExportDetail(detail).revision).toBe(4);
    expect(() => decodeExportDetail({ ...detail, state: "building" })).toThrow();
    expect(() => decodeExportDetail({
      ...detail,
      selection: { ...detail.selection, formats: ["pdf"] },
    })).toThrow();
    expect(() => decodeExportDetail({ ...detail, sha256: "/private/export" })).toThrow();
  });

  it("strictly validates shot enums, nullable contact, evidence, and cursors", () => {
    const shot = {
      id: "shot-1",
      timestampUs: 1000,
      predictionRevision: 2,
      rallyId: null,
      hitter: "near",
      shotKind: "drive",
      isVolley: false,
      outcome: "in_play",
      contact: [0, 9.75],
      speedMS: null,
      speedUnavailableReason: "calibration_unavailable",
      sourceEvidenceIds: ["evidence-1"],
    };
    expect(decodeShotDetail(shot)).toMatchObject({ id: "shot-1", contact: [0, 9.75] });
    expect(decodeShotPage({ items: [shot], nextCursor: null, predictionRevision: 2 }).items).toHaveLength(1);
    expect(() => decodeShotDetail({ ...shot, shotKind: "smash" })).toThrow();
    expect(() => decodeShotDetail({ ...shot, outcome: "unknown-outcome" })).toThrow();
    expect(() => decodeShotDetail({ ...shot, hitter: "Player A" })).toThrow();
    expect(() => decodeShotDetail({ ...shot, contact: [0, null] })).toThrow();
    expect(() => decodeShotDetail({ ...shot, sourceEvidenceIds: ["evidence-1", 2] })).toThrow();
    expect(() => decodeShotPage({ items: [shot], nextCursor: 12, predictionRevision: 2 })).toThrow();
    expect(() => decodeShotPage({ items: [{ ...shot, predictionRevision: 0 }], nextCursor: null, predictionRevision: 2 })).toThrow();
  });
});
