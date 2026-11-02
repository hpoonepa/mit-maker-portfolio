import { expect, it } from "vitest";
import { smoothSpeedSamples } from "./speed-display";
const readings = (values: number[], start = 0) => values.map((speedMps, i) => ({ speedMps, proxyTimestampUs: start+i*40_000, proxyEndTimestampUs: start+(i+1)*40_000, intervalStartUs: start+(i-1)*40_000, timestampUs: start+i*40_000, sourceFrameIndex: i }));
it("reduces frame jitter without changing constant speed or using future values", () => {
  expect(smoothSpeedSamples(readings([10,10,10]), []).map(s=>s.speedMps)).toEqual([10,10,10]);
  const first = smoothSpeedSamples(readings([10,11,9,40,10,11,9]), []);
  expect(Math.max(...first.map(s=>s.speedMps))).toBeLessThan(13);
  expect(first.slice(0,3)).toEqual(smoothSpeedSamples(readings([10,11,9]), []));
});
it("resets at impacts and gaps, preserving exact expiry", () => {
  const afterImpact = smoothSpeedSamples(readings([10,10,30,30]), [80_000]);
  expect(afterImpact[2].speedMps).toBe(30);
  const afterGap = smoothSpeedSamples([...readings([10,10]), ...readings([30], 1_000_000)], []);
  expect(afterGap.at(-1)!.speedMps).toBe(30);
  expect(afterGap[0].proxyEndTimestampUs).toBe(40_000);
});
