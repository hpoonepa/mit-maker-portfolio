import { describe, expect, it } from "vitest";

import {
  decodeBallObservationPage,
  decodeCorrectionConflicts,
  decodeMatchReport,
  decodeReviewItemPage,
  decodeTimelineItem,
  decodePlayerObservationPage,
  decodeReportList,
  decodeTimelinePage,
} from "./decoders";

const artifact = { availability: "available", jobId: "job-1", modelManifestIds: ["model-1"], sourceManifestIds: ["source-1"], stage: "ball", warnings: [] };

const report = {
  matchId: "match-1", revision: 4, predictionRevision: 7, calibrationRevision: 3,
  sections: { overview: { schemaVersion: 1, payload: { shot_count: 2 }, evidenceIds: ["ev-1"], hash: "hash", dependencyHash: "dep" } },
};

describe("complete generated analysis decoders", () => {
  it("accepts complete immutable reports and history while rejecting partial section contracts", () => {
    expect(decodeMatchReport(report)).toEqual(report);
    expect(decodeReportList({ items: [{ revision: 4, predictionRevision: 7, calibrationRevision: 3, createdAt: "2026-08-25T00:00:00Z", sectionHashes: { overview: "hash" } }], nextCursor: null }).items).toHaveLength(1);
    expect(() => decodeMatchReport({ ...report, sections: { overview: { schemaVersion: 1, payload: {}, evidenceIds: [] } } })).toThrow();
  });

  it("validates timeline cursor pages and observation links", () => {
    const page = { predictionRevision: 7, nextCursor: "signed-next", items: [{ id: "shot-1", kind: "shot", timestampUs: 2_000_000, endUs: null, evidenceIds: ["ev-1"], observationLinks: { ball: "ball-1" }, summary: { confidence: 0.8 } }] };
    expect(decodeTimelinePage(page).nextCursor).toBe("signed-next");
    expect(() => decodeTimelinePage({ ...page, items: [{ ...page.items[0], observationLinks: { ball: 42 } }] })).toThrow();
  });

  it("validates every generated player and ball observation field", () => {
    const player = { ambiguityReason: null, ambiguous: false, associationConfidence: 0.9, box: [1, 2, 3, 4], calibrationProvenance: "active", calibrationRevision: "3", detectionConfidence: 0.8, evidence: "observed", evidenceEndFrameIndex: 2, evidenceEndTimestampUs: 1_500_000, evidenceStartFrameIndex: 2, evidenceStartTimestampUs: 1_500_000, feet: [2, 4], keypoints: Array.from({ length: 17 }, (_, index) => ({ x: index, y: index + 1, confidence: 0.9 })), skeletonEdges: [[5, 7], [7, 9]], feetUncertaintyPx: 1, floor: [1, 2], floorUncertaintyM: 0.1, modelManifestId: "model", playerId: "A", sourceFrameIndex: 2, sourceManifestId: "source", sourceTimestampUs: 1_500_000, timestampUs: 1_500_000 };
    expect(decodePlayerObservationPage({ artifact: { ...artifact, stage: "players" }, startUs: 1_000_000, endUs: 2_000_000, nextCursor: null, items: [player] }).items).toHaveLength(1);
    const ball = { ambiguityReason: null, ambiguous: false, candidateCount: 1, candidates: [{ x: 20, y: 30, probability: 0.8, covariance: [[4, 0], [0, 9]] }], covariance: [[4, 0], [0, 9]], device: "mps", deviceFallback: false, evidence: "observed", evidenceEndFrameIndex: 2, evidenceEndTimestampUs: 1_500_000, evidenceStartFrameIndex: 2, evidenceStartTimestampUs: 1_500_000, modelManifestId: "ball-model", probability: 0.8, segmentId: "segment-1", sourceFrameIndex: 2, sourceHeight: 1080, sourceManifestId: "source", sourceTimestampUs: 1_500_000, sourceWidth: 1920, timestampUs: 1_500_000, visible: true, x: 20, y: 30 };
    expect(decodeBallObservationPage({ artifact, startUs: 1_000_000, endUs: 2_000_000, nextCursor: null, items: [ball] }).items).toHaveLength(1);
    expect(() => decodeBallObservationPage({ artifact, startUs: 1_000_000, endUs: 2_000_000, nextCursor: null, items: [{ ...ball, probability: "high" }] })).toThrow();
  });

  it("validates explicit correction conflict candidates", () => {
    const candidate = { candidateId: "candidate-a", timestampUs: 1_500_000, evidenceStartTimestampUs: 1_450_000, evidenceEndTimestampUs: 1_550_000, evidenceStartFrameIndex: 43, evidenceEndFrameIndex: 46, evidenceIds: ["ball-1"], label: "drive at 1.5 seconds" };
    expect(decodeCorrectionConflicts({ conflicts: [{ correctionId: "correction-1", reason: "target changed", candidateIds: ["candidate-a"], candidates: [candidate] }] }).conflicts[0].candidates).toHaveLength(1);
  });

  it("validates report-wide review pages and public evidence lookups", () => {
    const item = { id: "error-1", targetType: "error_candidate", kind: "tracking", timestampUs: 1_500_000, endUs: 1_550_000, confidence: null, issue: "accept", provenance: "unavailable", probabilities: {}, reasons: [], evidenceIds: ["ball-1"], evidenceStartTimestampUs: 1_450_000, evidenceEndTimestampUs: 1_550_000, evidenceStartFrameIndex: null, evidenceEndFrameIndex: null, invalidatedSections: ["errors"], invalidatedStats: ["review_counts"], summary: {}, commandTargets: { accept: { targetType: "error_candidate", targetId: "error-1", sourceTimestampUs: 1_500_000, sourceEvidenceIds: ["ball-1"], evidenceStartTimestampUs: 1_450_000, evidenceEndTimestampUs: 1_550_000, evidenceStartFrameIndex: null, evidenceEndFrameIndex: null } }, commandImpacts: { accept: { invalidatedSections: ["errors"], invalidatedStats: ["review_counts"] } }, reviewEntityType: "error_candidate", reviewEntityId: "error-1", reviewStatus: "pending" };
    expect(decodeReviewItemPage({ items: [item], nextCursor: null, reportRevision: 4 }).items[0].provenance).toBe("unavailable");
    expect(() => decodeReviewItemPage({ items: [{ ...item, reviewEntityType: "observation" }], nextCursor: null, reportRevision: 4 })).toThrow("reviewEntityType");
    expect(decodeTimelineItem({ id: "shot-1", kind: "shot", timestampUs: 1_500_000, evidenceIds: ["ball-1"], summary: {} }).id).toBe("shot-1");
  });
});
