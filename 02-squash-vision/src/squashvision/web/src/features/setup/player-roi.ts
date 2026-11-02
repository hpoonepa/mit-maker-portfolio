export interface PlayingAreaPoint { x: number; y: number }
export interface PlayingArea {
  revision: number;
  sourceSha256: string;
  frameSize: { width: number; height: number };
  points: PlayingAreaPoint[] | null;
  purpose: "player_detection_only";
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new TypeError("Playing area response is invalid");
  return value as Record<string, unknown>;
}

export function decodePlayingArea(value: unknown): PlayingArea {
  const area = record(value);
  const size = record(area.frameSize);
  if (!Number.isSafeInteger(area.revision) || (area.revision as number) < 0
    || typeof area.sourceSha256 !== "string" || !/^[a-f0-9]{64}$/i.test(area.sourceSha256)
    || !Number.isSafeInteger(size.width) || (size.width as number) <= 0
    || !Number.isSafeInteger(size.height) || (size.height as number) <= 0
    || area.purpose !== "player_detection_only") throw new TypeError("Playing area response is invalid");
  if (area.points !== null) {
    if (!Array.isArray(area.points) || area.points.length < 3 || area.points.length > 16) throw new TypeError("Playing area points are invalid");
    for (const candidate of area.points) {
      const point = record(candidate);
      if (typeof point.x !== "number" || !Number.isFinite(point.x) || point.x < 0 || point.x > (size.width as number)
        || typeof point.y !== "number" || !Number.isFinite(point.y) || point.y < 0 || point.y > (size.height as number)) throw new TypeError("Playing area points are outside the source image");
    }
    if (!validPlayingArea(area.points as PlayingAreaPoint[])) throw new TypeError("Playing area polygon is invalid");
  }
  return value as PlayingArea;
}

export function validPlayingArea(points: PlayingAreaPoint[]): boolean {
  if (points.length < 3 || points.length > 16) return false;
  // All remaining vertices must lie on the same interior side of each edge.
  let direction = 0;
  for (let index = 0; index < points.length; index += 1) {
    const start = points[index];
    const end = points[(index + 1) % points.length];
    for (let offset = 2; offset < points.length; offset += 1) {
      const point = points[(index + offset) % points.length];
      const cross = (end.x - start.x) * (point.y - start.y) - (end.y - start.y) * (point.x - start.x);
      if (!Number.isFinite(cross) || Math.abs(cross) < 1) return false;
      const side = Math.sign(cross);
      if (direction !== 0 && direction !== side) return false;
      direction = side;
    }
  }
  return true;
}
