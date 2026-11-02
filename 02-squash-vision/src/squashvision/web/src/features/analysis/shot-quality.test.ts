import { describe, expect, it } from "vitest";
import { gradeShot, coachingSummary } from "./shot-quality";
import type { ReviewShot } from "./shot-model";

const shot = (patch: Partial<ReviewShot> = {}): ReviewShot => ({ id: "s1", contactUs: 1_000_000, hitter: "A", type: "drive", origin: "reviewed", confidence: 1, contactImage: null, playerPosition: [1, 5], opponentPosition: [5, 5], wall: null, landing: { timeUs: 2_000_000, image: null, position: [.15, 7.5] }, notes: "", ...patch });
describe("explainable shot ratings", () => {
  it("rewards tight good length over a loose short drive", () => {
    const good = gradeShot(shot());
    const weak = gradeShot(shot({ landing: { timeUs: 2_000_000, image: null, position: [2, 4] } }));
    expect(good.quality).toBeGreaterThan(8);
    expect(weak.quality).toBeLessThan(5);
    expect(good.factors.map(f => f.label)).toEqual(["Tightness", "Length"]);
    expect(good.reasons.join(" ")).toMatch(/tight/i);
  });
  it("does not pretend unknown shots or missing landings have a score", () => {
    expect(gradeShot(shot({ type: "unknown" })).quality).toBeNull();
    expect(gradeShot(shot({ landing: null })).quality).toBeNull();
    expect(gradeShot(shot({ origin: "automatic", confidence: .2 })).quality).toBeNull();
  });
  it("keeps retrieval difficulty distinct and unavailable without opponent evidence", () => {
    expect(gradeShot(shot({ opponentPosition: null })).difficulty).toBeNull();
    const close = gradeShot(shot({ opponentPosition: [.2, 7.3] }));
    const far = gradeShot(shot({ opponentPosition: [6, 1] }));
    expect(far.quality).toBe(close.quality);
    expect(far.difficulty!).toBeGreaterThan(close.difficulty!);
  });
  it("scores a drop for shortness and supported height, with tin contact never rewarded", () => {
    const drop = shot({ type: "drop", landing: { timeUs: 2_000_000, image: null, position: [.1, .8] }, wall: { timeUs: 1_400_000, image: null, position: [.2, .65] } });
    expect(gradeShot(drop).quality).toBeGreaterThan(8);
    expect(gradeShot(drop).factors).toHaveLength(3);
    expect(gradeShot({ ...drop, wall: { ...drop.wall!, position: [.2, .4] } }).quality).toBe(0);
    expect(gradeShot({ ...drop, wall: null }).partial).toBe(true);
  });
  it("summarizes only rated reviewed/usable shots and links weak examples", () => {
    const weak = shot({ id: "weak", landing: { timeUs: 2_000_000, image: null, position: [2, 4] } });
    const summary = coachingSummary([shot(), weak, shot({ id: "missing", landing: null })]);
    expect(summary.ratedCount).toBe(2);
    expect(summary.weakest[0].shot.id).toBe("weak");
    expect(summary.insights.join(" ")).toMatch(/1 of 2.*short/i);
  });
  it("never praises a tin impact as tight and well placed",()=>{
    const result=coachingSummary([shot({wall:{timeUs:1_400_000,image:null,position:[.2,.4]}})]);
    expect(result.insights.join(" ")).not.toMatch(/tight and well placed/i);
  });
  it("estimates broad placement for an unclassified tracked shot without claiming a shot type",()=>{
    const automatic=shot({type:"unknown",origin:"automatic",confidence:.46});
    expect(gradeShot(automatic).quality).toBeGreaterThan(8);
    expect(gradeShot(automatic).partial).toBe(true);
    expect(gradeShot({...automatic,confidence:.25}).quality).toBeNull();
    expect(gradeShot({...automatic,landing:{timeUs:2_000_000,image:null,position:[2,4]}}).quality).toBeNull();
  });
  it("rates a volleyed return from calibrated wall placement without inventing a bounce",()=>{
    const volleyed=shot({landing:null,wall:{timeUs:1_300_000,image:null,position:[.2,1.4]}});
    const grade=gradeShot(volleyed);
    expect(grade.quality).toBeGreaterThan(7);
    expect(grade.basis).toBe("wall");
    expect(grade.partial).toBe(true);
    expect(grade.difficulty).toBeNull();
    expect(grade.factors.some(f=>f.label==="Length")).toBe(false);
    expect(coachingSummary([volleyed]).ratedCount).toBe(1);
  });
  it("uses shot-specific wall targets instead of penalizing a crosscourt for a central wall impact",()=>{
    const base=shot({landing:null,wall:{timeUs:1_300_000,image:null,position:[3.2,1.4]}});
    expect(gradeShot({...base,type:"crosscourt"}).quality!).toBeGreaterThan(gradeShot(base).quality!);
    expect(gradeShot({...base,type:"drop",wall:{...base.wall!,position:[.2,.3]}}).quality).toBe(0);
  });
  it("keeps wall-only scores out of bounce averages, rankings and placement denominators",()=>{
    const loose=shot({id:"loose",landing:{timeUs:2_000_000,image:null,position:[2,4]}});
    const wall=shot({id:"wall",landing:null,wall:{timeUs:1_300_000,image:null,position:[.1,1.4]}});
    const summary=coachingSummary([loose,wall]);
    expect(summary.ratedCount).toBe(2);
    expect(summary.wallOnlyCount).toBe(1);
    expect(summary.bounceRatedCount).toBe(1);
    expect(summary.average).toBe(gradeShot(loose).quality);
    expect(summary.weakest.map(s=>s.shot.id)).toEqual(["loose"]);
    expect(summary.insights.join(" ")).toMatch(/1 of 1.*side wall/);
  });
});
