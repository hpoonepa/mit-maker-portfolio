import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { components } from "../../api/types.generated";
import type { ReviewShortcut } from "./ReviewQueue";
import type { ReviewItem } from "./review-model";

type CorrectionCommand = components["schemas"]["CorrectionCommand"];
type CorrectionCommandType = components["schemas"]["CorrectionCommandType"];
type CorrectionConflict = components["schemas"]["CorrectionConflictDetail"];

interface ShortcutRequest {
  version: number;
  command: ReviewShortcut;
}

interface CorrectionEditorProps {
  matchId: string;
  item: ReviewItem;
  reportRevision: number;
  pending: boolean;
  conflictRevision?: number | null;
  shortcut?: ShortcutRequest | null;
  reapplicationConflicts?: CorrectionConflict[];
  conflictResolutionPending?: boolean;
  onSubmit: (command: CorrectionCommand) => void;
  onRebase?: () => void;
  onDiscard?: () => void;
  onResolveConflict?: (correctionId: string, candidateId: string | null, resolution: "select" | "reject") => void;
  onSeekConflictEvidence?: (timestampUs: number, evidenceId: string) => void;
  onCommandChange?: (command: CorrectionCommandType) => void;
}

interface ReapplicationConflictControlsProps {
  conflicts: CorrectionConflict[];
  onResolveConflict?: (correctionId: string, candidateId: string | null, resolution: "select" | "reject") => void;
  onSeekConflictEvidence?: (timestampUs: number, evidenceId: string) => void;
  pending?: boolean;
}

export function ReapplicationConflictControls({ conflicts, pending = false, onResolveConflict, onSeekConflictEvidence }: ReapplicationConflictControlsProps) {
  const [candidateByConflict, setCandidateByConflict] = useState<Record<string, string>>({});

  return conflicts.map((conflict) => (
    <fieldset key={conflict.correctionId} className="reapplication-conflict">
      <legend>{conflict.reason}</legend>
      {(conflict.candidates ?? []).map((candidate) => <div key={candidate.candidateId} className="conflict-candidate"><label><input type="radio" name={conflict.correctionId} value={candidate.candidateId} checked={candidateByConflict[conflict.correctionId] === candidate.candidateId} onChange={() => setCandidateByConflict((current) => ({ ...current, [conflict.correctionId]: candidate.candidateId }))} />{candidate.label} · {candidate.evidenceStartTimestampUs / 1_000_000}s–{candidate.evidenceEndTimestampUs / 1_000_000}s</label><button type="button" disabled={candidate.evidenceIds.length === 0} onClick={() => { const evidenceId = candidate.evidenceIds[0]; if (evidenceId !== undefined) onSeekConflictEvidence?.(candidate.timestampUs, evidenceId); }}>Seek candidate evidence</button></div>)}
      <button type="button" disabled={pending || candidateByConflict[conflict.correctionId] === undefined} onClick={() => onResolveConflict?.(conflict.correctionId, candidateByConflict[conflict.correctionId] ?? null, "select")}>Select candidate</button>
      <button type="button" className="button-danger" disabled={pending} onClick={() => onResolveConflict?.(conflict.correctionId, null, "reject")}>Reject reapplication</button>
    </fieldset>
  ));
}

const COMMAND_LABELS: Array<[CorrectionCommandType, string]> = [
  ["accept", "Accept prediction"],
  ["reject", "Reject prediction"],
  ["change_hitter", "Change hitter"],
  ["change_shot_type", "Change primary shot"],
  ["adjust_contact_time", "Adjust contact time"],
  ["change_outcome", "Change outcome"],
  ["ball_control_point", "Set ball control point"],
  ["split_rally", "Split rally"],
  ["merge_rallies", "Merge rallies"],
];

const SHOT_TYPES = ["unknown", "serve", "drive", "boast", "drop", "lob", "kill"] as const;
const OUTCOMES = ["unknown", "in_play", "winner", "error", "let", "stroke"] as const;

function canonicalShotType(value: string | null): (typeof SHOT_TYPES)[number] {
  if (value === "straight_drive" || value === "crosscourt_drive") return "drive";
  return SHOT_TYPES.find((candidate) => candidate === value) ?? "unknown";
}

function canonicalOutcome(value: string | null): (typeof OUTCOMES)[number] {
  if (value === "continuation" || value === "continues") return "in_play";
  return OUTCOMES.find((candidate) => candidate === value) ?? "unknown";
}


function summaryString(item: ReviewItem, ...names: string[]): string | null {
  for (const name of names) {
    const value = item.summary[name];
    if (typeof value === "string") return value;
  }
  return null;
}

function summaryNumber(item: ReviewItem, ...names: string[]): number | null {
  for (const name of names) {
    const value = item.summary[name];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}
function commandForIssue(issue: string): CorrectionCommandType {
  if (issue === "hitter" || issue === "identity" || issue === "player_identity") return "change_hitter";
  if (issue === "shot_type" || issue === "type") return "change_shot_type";
  if (issue === "outcome") return "change_outcome";
  if (issue === "rally_boundary") return "split_rally";
  if (issue === "ball_seam") return "ball_control_point";
  return "accept";
}
function applicableCommand(item: ReviewItem, requested = commandForIssue(item.issue)): CorrectionCommandType {
  if (item.commandTargets[requested] !== undefined) return requested;
  return COMMAND_LABELS.find(([command]) => item.commandTargets[command] !== undefined)?.[0] ?? "accept";
}



export function CorrectionEditor({
  matchId,
  item,
  reportRevision,
  pending,
  conflictRevision = null,
  shortcut = null,
  conflictResolutionPending = false,
  reapplicationConflicts = [],
  onSubmit,
  onRebase,
  onDiscard,
  onResolveConflict,
  onSeekConflictEvidence,
  onCommandChange,
}: CorrectionEditorProps) {
  const [commandType, setCommandType] = useState<CorrectionCommandType>(() => applicableCommand(item));
  const [hitter, setHitter] = useState(summaryString(item, "hitter") ?? "near");
  const [shotType, setShotType] = useState<(typeof SHOT_TYPES)[number]>(() => canonicalShotType(summaryString(item, "shot_type", "shotKind")));
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]>(() => canonicalOutcome(summaryString(item, "outcome")));
  const [contactSeconds, setContactSeconds] = useState((item.timestampUs / 1_000_000).toFixed(3));
  const [xM, setXM] = useState("3.2");
  const [yM, setYM] = useState("4.875");
  const [mergeTarget, setMergeTarget] = useState("");
  const [reason, setReason] = useState("");


  useEffect(() => {
    setCommandType(applicableCommand(item));
    setHitter(summaryString(item, "hitter") ?? "near");
    setShotType(canonicalShotType(summaryString(item, "shot_type", "shotKind")));
    setOutcome(canonicalOutcome(summaryString(item, "outcome")));
    setContactSeconds((item.timestampUs / 1_000_000).toFixed(3));
    setReason("");
  }, [item.id]);
  useEffect(() => {
    onCommandChange?.(commandType);
  }, [commandType, onCommandChange]);


  useEffect(() => {
    if (shortcut === null) return;
    if (shortcut.command === "accept" || shortcut.command === "reject") {
      if (item.commandTargets[shortcut.command] !== undefined) setCommandType(shortcut.command);
      return;
    }
    if (shortcut.command === "cycle_hitter") {
      if (item.commandTargets.change_hitter === undefined) return;
      setCommandType("change_hitter");
      setHitter((current) => current === "near" ? "far" : "near");
      return;
    }
    if (shortcut.command === "cycle_shot") {
      if (item.commandTargets.change_shot_type === undefined) return;
      setCommandType("change_shot_type");
      setShotType((current) => SHOT_TYPES[(SHOT_TYPES.indexOf(current) + 1) % SHOT_TYPES.length] ?? "unknown");
      return;
    }
    if (item.commandTargets.change_outcome === undefined) return;
    setCommandType("change_outcome");
    setOutcome((current) => OUTCOMES[(OUTCOMES.indexOf(current) + 1) % OUTCOMES.length] ?? "unknown");
  }, [item, shortcut]);

  useEffect(() => {
    const target = item.commandTargets[commandType];
    if (target !== undefined) setContactSeconds((target.sourceTimestampUs / 1_000_000).toFixed(3));
  }, [commandType, item]);

  const resetDraft = (): void => {
    setCommandType(applicableCommand(item));
    setHitter(summaryString(item, "hitter") ?? "near");
    setShotType(canonicalShotType(summaryString(item, "shot_type", "shotKind")));
    setOutcome(canonicalOutcome(summaryString(item, "outcome")));
    const target = item.commandTargets[applicableCommand(item)];
    setContactSeconds(((target?.sourceTimestampUs ?? item.timestampUs) / 1_000_000).toFixed(3));
    setXM("3.2");
    setYM("4.875");
    setMergeTarget("");
    setReason("");
  };

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const target = item.commandTargets[commandType];
    if (target === undefined) return;
    let payload: Record<string, unknown> = {};
    if (commandType === "change_hitter") payload = { hitter };
    else if (commandType === "change_shot_type") payload = { shot_type: shotType };
    else if (commandType === "adjust_contact_time") payload = { source_timestamp_us: Math.round(Number(contactSeconds) * 1_000_000) };
    else if (commandType === "change_outcome") payload = { outcome };
    else if (commandType === "ball_control_point") payload = { x_m: Number(xM), y_m: Number(yM) };
    else if (commandType === "split_rally") payload = { split_timestamp_us: Math.round(Number(contactSeconds) * 1_000_000) };
    else if (commandType === "merge_rallies") payload = { other_target_id: mergeTarget };
    onSubmit({
      commandType,
      expectedReportRevision: reportRevision,
      matchId,
      payload,
      reason,
      sourceEvidenceIds: target.sourceEvidenceIds,
      sourceTimestampUs: target.sourceTimestampUs,
      targetId: target.targetId,
      reviewEntityType: item.reviewEntityType,
      reviewEntityId: item.reviewEntityId,
      targetType: target.targetType,
    });
  };

  return (
    <section className="correction-editor" aria-labelledby="correction-editor-title">
      <h2 id="correction-editor-title">Correct selected evidence</h2>
      <form onSubmit={submit}>
        <label>Correction<select value={commandType} onChange={(event) => setCommandType(COMMAND_LABELS.find(([candidate]) => candidate === event.currentTarget.value)?.[0] ?? "accept")}>{COMMAND_LABELS.filter(([value]) => item.commandTargets[value] !== undefined).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {commandType === "change_hitter" ? <label>Hitter<select value={hitter} onChange={(event) => setHitter(event.currentTarget.value)}><option value="near">Player A</option><option value="far">Player B</option></select></label> : null}
        {commandType === "change_shot_type" ? <label>Primary shot<select value={shotType} onChange={(event) => setShotType(canonicalShotType(event.currentTarget.value))}>{SHOT_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label> : null}
        {commandType === "change_outcome" ? <label>Outcome<select value={outcome} onChange={(event) => setOutcome(canonicalOutcome(event.currentTarget.value))}>{OUTCOMES.map((value) => <option key={value}>{value}</option>)}</select></label> : null}
        {commandType === "adjust_contact_time" || commandType === "split_rally" ? <label>{commandType === "split_rally" ? "Split time (seconds)" : "Contact time (seconds)"}<input type="number" step="0.001" min="0" value={contactSeconds} onChange={(event) => setContactSeconds(event.currentTarget.value)} required /></label> : null}
        {commandType === "ball_control_point" ? <div className="correction-coordinate"><label>Court X (m)<input type="number" step="0.01" min="0" max="6.4" value={xM} onChange={(event) => setXM(event.currentTarget.value)} required /></label><label>Court Y (m)<input type="number" step="0.01" min="0" max="9.75" value={yM} onChange={(event) => setYM(event.currentTarget.value)} required /></label></div> : null}
        {commandType === "merge_rallies" ? <label>Adjacent rally ID<input value={mergeTarget} onChange={(event) => setMergeTarget(event.currentTarget.value)} required /></label> : null}
        <label>Reason<textarea value={reason} onChange={(event) => setReason(event.currentTarget.value)} required /></label>
        <button type="submit" className="button-primary" disabled={pending || item.commandTargets[commandType] === undefined}>{pending ? "Saving correction…" : "Save correction"}</button>
        {pending ? <p className="pending-label" role="status">Saving a new revision. The current report stays unchanged until saving finishes.</p> : null}
      </form>
      {conflictRevision !== null ? (
        <div className="correction-conflict" role="alert">
          <strong>A newer report is available</strong>
          <p>Revision {conflictRevision} is current. Your draft and selected time have been kept.</p>
          <div><button type="button" onClick={onRebase}>Rebase onto revision {conflictRevision}</button><button type="button" className="button-danger" onClick={() => { resetDraft(); onDiscard?.(); }}>Discard local draft</button></div>
        </div>
      ) : null}
      <ReapplicationConflictControls conflicts={reapplicationConflicts} pending={conflictResolutionPending} onResolveConflict={onResolveConflict} onSeekConflictEvidence={onSeekConflictEvidence} />
    </section>
  );
}
