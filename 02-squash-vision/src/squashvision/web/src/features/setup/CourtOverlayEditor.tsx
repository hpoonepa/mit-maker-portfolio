import { useId, useRef, useState } from "react";

import type { CalibrationKeypoint, CalibrationSize } from "../../api/decoders";

interface Bounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface ClientPoint {
  x: number;
  y: number;
}

export function videoContentRect(container: Bounds, intrinsic: CalibrationSize): Bounds {
  if (container.width <= 0 || container.height <= 0 || intrinsic.width <= 0 || intrinsic.height <= 0) {
    return { ...container };
  }
  const scale = Math.min(container.width / intrinsic.width, container.height / intrinsic.height);
  const width = intrinsic.width * scale;
  const height = intrinsic.height * scale;
  return {
    left: container.left + (container.width - width) / 2,
    top: container.top + (container.height - height) / 2,
    width,
    height,
  };
}

export function clientPointToImage(
  point: ClientPoint,
  content: Bounds,
  intrinsic: CalibrationSize,
): ClientPoint {
  if (content.width <= 0 || content.height <= 0) return { x: 0, y: 0 };
  const normalizedX = Math.max(0, Math.min(1, (point.x - content.left) / content.width));
  const normalizedY = Math.max(0, Math.min(1, (point.y - content.top) / content.height));
  return {
    x: Math.round(normalizedX * intrinsic.width),
    y: Math.round(normalizedY * intrinsic.height),
  };
}

interface CourtOverlayEditorProps {
  frameSize: CalibrationSize;
  keypoints: CalibrationKeypoint[];
  proposalKeypoints: CalibrationKeypoint[];
  videoSrc: string;
  selectedTimestampSeconds?: number;
  onChange: (keypoints: CalibrationKeypoint[]) => void;
}

function pointsAttribute(points: CalibrationKeypoint[]): string {
  return points.map((point) => `${point.image.x},${point.image.y}`).join(" ");
}

export function calibrationHitRadius(sourceWidth: number): number {
  return Math.max(44, (Math.max(1, sourceWidth) * 22) / 320);
}

export function CourtOverlayEditor({
  frameSize,
  keypoints,
  proposalKeypoints,
  videoSrc,
  selectedTimestampSeconds = 0,
  onChange,
}: CourtOverlayEditorProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const keyboardHelpId = useId();

  const movePoint = (index: number, x: number, y: number): void => {
    onChange(
      keypoints.map((point, pointIndex) =>
        pointIndex === index
          ? {
              ...point,
              image: {
                x: Math.max(0, Math.min(frameSize.width, x)),
                y: Math.max(0, Math.min(frameSize.height, y)),
              },
            }
          : point,
      ),
    );
  };

  const pointerPoint = (clientX: number, clientY: number): ClientPoint | null => {
    const svg = svgRef.current;
    if (svg === null) return null;
    const rect = svg.getBoundingClientRect();
    const content = videoContentRect(
      { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      frameSize,
    );
    return clientPointToImage({ x: clientX, y: clientY }, content, frameSize);
  };

  return (
    <div className="court-editor">
      <div ref={stageRef} className="video-stage" data-dragging={draggingIndex !== null}>
        <video
          src={videoSrc}
          controls
          preload="metadata"
          aria-label="Match calibration video"
          onLoadedMetadata={(event) => {
            if (Number.isFinite(selectedTimestampSeconds) && selectedTimestampSeconds >= 0) {
              event.currentTarget.currentTime = selectedTimestampSeconds;
            }
          }}
        />
        <svg
          ref={svgRef}
          className="court-overlay"
          viewBox={`0 0 ${frameSize.width} ${frameSize.height}`}
          preserveAspectRatio="xMidYMid meet"
          aria-label="Court calibration points"
          onPointerMove={(event) => {
            if (draggingIndex === null) return;
            const point = pointerPoint(event.clientX, event.clientY);
            if (point !== null) movePoint(draggingIndex, point.x, point.y);
          }}
          onPointerUp={() => setDraggingIndex(null)}
          onPointerCancel={() => setDraggingIndex(null)}
        >
          <polygon
            data-testid="proposal-court-lines"
            data-line-style="dashed"
            className="court-lines proposal-lines"
            points={pointsAttribute(proposalKeypoints)}
          />
          <polygon
            data-testid="manual-court-lines"
            data-line-style="solid"
            className="court-lines manual-lines"
            points={pointsAttribute(keypoints)}
          />
          {keypoints.map((point, index) => (
            <g
              key={point.label}
              role="button"
              tabIndex={0}
              aria-label={`Move ${point.label} calibration point`}
              aria-describedby={keyboardHelpId}
              aria-pressed={selectedIndex === index}
              className="calibration-control"
              onPointerDown={(event) => {
                setDraggingIndex(index);
                setSelectedIndex(index);
                event.preventDefault();
                event.currentTarget.setPointerCapture?.(event.pointerId);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedIndex((current) => current === index ? null : index);
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setSelectedIndex(null);
                  return;
                }
                const amount = event.shiftKey ? 10 : 1;
                const delta: Record<string, ClientPoint> = {
                  ArrowLeft: { x: -amount, y: 0 },
                  ArrowRight: { x: amount, y: 0 },
                  ArrowUp: { x: 0, y: -amount },
                  ArrowDown: { x: 0, y: amount },
                };
                const change = delta[event.key];
                if (change === undefined) return;
                event.preventDefault();
                setSelectedIndex(index);
                movePoint(index, point.image.x + change.x, point.image.y + change.y);
              }}
            >
              <circle className="calibration-hit-target" cx={point.image.x} cy={point.image.y} r={calibrationHitRadius(frameSize.width)} />
              <circle className="calibration-handle" cx={point.image.x} cy={point.image.y} r={12} />
              <text
                className="calibration-label"
                x={Math.min(frameSize.width - 24, point.image.x + 18)}
                y={Math.max(30, Math.min(frameSize.height - 32, point.image.y - 18))}
                textAnchor={point.image.x > frameSize.width - 180 ? "end" : "start"}
              >
                {point.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <p id={keyboardHelpId} className="court-editor-help">Drag a corner, or press Enter or Space to select it and use arrow keys to adjust. Hold Shift for 10-pixel steps; Escape clears selection.</p>
      <div className="editor-actions">
        <button type="button" className="button-secondary" onClick={() => onChange(proposalKeypoints)}>
          Reset to automatic proposal
        </button>
        <button
          type="button"
          className="button-secondary"
          onClick={() => void stageRef.current?.requestFullscreen()}
        >
          Fullscreen court editor
        </button>
        <span className="line-legend"><i className="legend-proposal" />Automatic proposal</span>
        <span className="line-legend"><i className="legend-manual" />Manual / saved</span>
      </div>
    </div>
  );
}
