import { expect, it } from "vitest";
import { projectWall, validWallCalibration } from "./wall-calibration";
const calibration = { points: [[.2, .8], [.8, .8], [.7, .3], [.3, .3]] as [number, number][], tinHeightM: .48 };
it("maps floor/service corners and perspective center to metric wall coordinates", () => {
  expect(projectWall(calibration, [.2, .8])![0]).toBeCloseTo(0);
  expect(projectWall(calibration, [.2, .8])![1]).toBeCloseTo(0);
  expect(projectWall(calibration, [.7, .3])![0]).toBeCloseTo(6.4);
  expect(projectWall(calibration, [.7, .3])![1]).toBeCloseTo(1.78);
  expect(projectWall(calibration, [.5, .5])![0]).toBeCloseTo(3.2);
});
it("rejects crossing, collinear, reversed and out-of-frame calibration or wall points", () => {
  expect(validWallCalibration(calibration)).toBe(true);
  expect(validWallCalibration({ ...calibration, points: [[0,0],[1,1],[0,1],[1,0]] })).toBe(false);
  expect(validWallCalibration({ ...calibration, points: [[0,0],[.2,0],[.4,0],[.6,0]] })).toBe(false);
  expect(projectWall(calibration, [1.2,.5])).toBeNull();
  expect(projectWall(calibration, [0,.5])).toBeNull();
});
