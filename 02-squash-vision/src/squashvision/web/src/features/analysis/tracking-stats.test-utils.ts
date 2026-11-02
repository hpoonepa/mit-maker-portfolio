import type { TrackingStats } from "./tracking-stats";

export function trackingStatsFixture(overrides: Partial<TrackingStats> = {}): TrackingStats {
  return {
    reportRevision: 2, predictionRevision: 1, calibrationRevision: 3, calibrationAvailable: true, calibrationReason: null,
    startUs: 0, endUs: 20_000_000,
    players: [
      { playerId: "A", distanceM: 12.4, trackedSeconds: 10, coverage: .5, observedSamples: 251, usedSamples: 240, excludedSamples: 11, contactCount: 1, identityVerified: false },
      { playerId: "B", distanceM: 8.2, trackedSeconds: 8, coverage: .4, observedSamples: 201, usedSamples: 190, excludedSamples: 11, contactCount: 1, identityVerified: false },
    ],
    contacts: [
      { id: "contact-a", timestampUs: 12_520_000, proxyTimestampUs: 12_500_000, sourceFrameIndex: 313, hitter: "A", hitterConfidence: .8, confidence: .7, position: [1, 2], positionMethod: "hitter_feet_at_contact", reason: null, reviewRequired: true },
      { id: "contact-b", timestampUs: 14_040_000, proxyTimestampUs: 14_033_333, sourceFrameIndex: 351, hitter: "B", hitterConfidence: .9, confidence: .85, position: [5, 8], positionMethod: "hitter_feet_at_contact", reason: null, reviewRequired: false },
      { id: "contact-unknown", timestampUs: 16_000_000, proxyTimestampUs: null, sourceFrameIndex: null, hitter: null, hitterConfidence: 0, confidence: .3, position: null, positionMethod: "hitter_feet_at_contact", reason: "unknown_hitter", reviewRequired: true },
    ],
    ballSpeed: { medianMps: 14, p90Mps: 18, sampleCount: 50, excludedSamples: 449, trackedSeconds: 2, coverage: .1, method: "floor_plane_projection", reason: null },
    coordinateSystem: "front_left_x_right_y_back_metres", limitations: ["Ball height is unavailable.", "Player identity review pending."],
    ...overrides,
  };
}
