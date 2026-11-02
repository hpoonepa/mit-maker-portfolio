import { describe, expect, it } from "vitest";

import type { components } from "../../api/types.generated";
import { buildReviewQueue } from "./review-model";

type TimelineItem = components["schemas"]["TimelineItem"];

const events: TimelineItem[] = [
  { id: "type", kind: "shot", timestampUs: 10_000_000, evidenceIds: ["type-evidence"], summary: { confidence: 0.2, review_required: true, issue: "shot_type", invalidatedSections: ["shots"], invalidatedStats: ["shot_type_counts"] } },
  { id: "boundary", kind: "rally", timestampUs: 20_000_000, evidenceIds: ["boundary-evidence"], summary: { confidence: 0.8, review_required: true, issue: "rally_boundary", invalidatedSections: ["overview", "rallies"], invalidatedStats: ["rally_count"] } },
  { id: "accepted", kind: "error_candidate", timestampUs: 5_000_000, evidenceIds: ["accepted-evidence"], summary: { confidence: 0.1, review_status: "accepted" } },
];

describe("review queue", () => {
  it("prioritizes downstream impact, then confidence, then timestamp and excludes resolved items", () => {
    const queue = buildReviewQueue([], events);
    expect(queue.map((item) => item.id)).toEqual(["boundary", "type"]);
    expect(queue.every((item) => item.id !== "accepted")).toBe(true);
    expect(queue[0].invalidatedSections).toEqual(expect.arrayContaining(["rallies", "overview"]));
    expect(queue[0].provenance).toBe("unavailable");
  });

  it("retains the canonical review entity when the display event has a different ID", () => {
    const queue = buildReviewQueue([], [{
      id: "display-event-7",
      kind: "shot",
      timestampUs: 30_000_000,
      evidenceIds: ["display-event-7"],
      summary: {
        confidence: 0.2,
        reviewRequired: true,
        reviewEntityType: "shot",
        reviewEntityId: "canonical-shot-12",
      },
    }]);

    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      id: "display-event-7",
      reviewEntityType: "shot",
      reviewEntityId: "canonical-shot-12",
    });
  });

  it("deduplicates by review entity type and ID rather than display event ID", () => {
    const sharedDisplayEvents: TimelineItem[] = [
      {
        id: "shared-display-id",
        kind: "shot",
        timestampUs: 30_000_000,
        evidenceIds: ["shot-evidence"],
        summary: {
          confidence: 0.2,
          reviewRequired: true,
          reviewEntityType: "shot",
          reviewEntityId: "entity-1",
        },
      },
      {
        id: "shared-display-id",
        kind: "error",
        timestampUs: 31_000_000,
        evidenceIds: ["error-evidence"],
        summary: {
          confidence: 0.1,
          reviewRequired: true,
          reviewEntityType: "error_candidate",
          reviewEntityId: "entity-1",
        },
      },
    ];

    const queue = buildReviewQueue([], sharedDisplayEvents);

    expect(queue).toHaveLength(2);
    expect(queue.map(({ reviewEntityType, reviewEntityId }) => `${reviewEntityType}:${reviewEntityId}`).sort()).toEqual([
      "error_candidate:entity-1",
      "shot:entity-1",
    ]);
  });

  it("deduplicates timeline fallbacks that identify the same canonical review entity", () => {
    const queue = buildReviewQueue([], [
      {
        id: "display-event-a",
        kind: "shot",
        timestampUs: 30_000_000,
        evidenceIds: ["evidence-a"],
        summary: {
          confidence: 0.2,
          reviewRequired: true,
          reviewEntityType: "shot",
          reviewEntityId: "canonical-shot-12",
        },
      },
      {
        id: "display-event-b",
        kind: "shot",
        timestampUs: 31_000_000,
        evidenceIds: ["evidence-b"],
        summary: {
          confidence: 0.1,
          reviewRequired: true,
          reviewEntityType: "shot",
          reviewEntityId: "canonical-shot-12",
        },
      },
    ]);

    expect(queue).toHaveLength(1);
    expect(queue[0].id).toBe("display-event-a");
  });
});
