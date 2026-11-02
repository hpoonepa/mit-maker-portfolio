import React, { useEffect, useRef, useState } from "react";
import protein from "../lib/protein.json";

type Profile = "antibody_epitope" | "designability" | "exposure_only";
type Finding = { code: string; message: string; severity: string; residue?: string | null };
type CheckRecord = {
  verdict: string;
  site: { keys: string[]; hotspot_spec: string };
  findings: Finding[];
};
type Patch = {
  score: number;
  residues: string[];
  components: Record<string, number>;
  mean_relative_sasa: number;
  structural_rank?: number;
  structural_score?: number;
  evidence?: { score: number; supported_residues: string[]; refuted_residues: string[]; conflicting_residues: string[]; sources: string[]; reviewers: string[]; status: string };
};
type Metrics = { macro_auroc: number; macro_auprc: number };
type AnalyzeResponse = {
  schema_version: number | string;
  target: { id: string; chains: string[]; chain: string; assembly_id: string | null };
  proposal: { patches: Patch[]; weight_profile: string; ranking?: string };
  checks: Array<{ rank: number; residues: string[]; record: CheckRecord }>;
  selected_check: CheckRecord | null;
  evidence?: {
    status: string; affects: string; llm_trained: boolean;
    extraction?: {
      method: string;
      drafts: Array<{ residues: string[]; claim: string; source: string; quote: string; reviewed: false; span_start: number; span_end: number; [key: string]: unknown }>;
      review_required: boolean;
    };
  };
  validation: {
    status: string;
    model_type: string;
    split_instances?: { train: number; val: number; test: number };
    split_clusters?: { train: number; val: number; test: number };
    evaluation?: { fitted: Metrics; exposure_only: Metrics };
    limitations?: string[];
  };
};
const API_DEFAULT = "http://127.0.0.1:18766";
const MAX_BYTES = 8 * 1024 * 1024;

function csvFromResult(result: AnalyzeResponse): string {
  const rows = [["kind", "rank", "score", "residues", "relative_sasa", "components", "verdict", "findings", "structural_rank", "structural_score", "evidence"]];
  for (const [index, patch] of result.proposal.patches.entries()) {
    const check = result.checks.find((item) => item.rank === index + 1)?.record;
    rows.push([
      "proposal", String(index + 1), String(patch.score), patch.residues.join(";"),
      String(patch.mean_relative_sasa), JSON.stringify(patch.components), check?.verdict ?? "Not checked",
      (check?.findings ?? []).map((f) => `${f.severity}: ${f.code}: ${f.message}`).join(" | "),
      String(patch.structural_rank ?? ""), String(patch.structural_score ?? ""), JSON.stringify(patch.evidence ?? {}),
    ]);
  }
  if (result.selected_check) {
    const selected = result.selected_check;
    rows.push(["selected_hotspots", "", "", selected.site.keys.join(";"), "", "", selected.verdict,
      selected.findings.map((f) => `${f.severity}: ${f.code}: ${f.message}`).join(" | "), "", "", ""]);
  }
  return rows.map((row) => row.map((cell) => {
    // Uploaded chain identifiers and findings are untrusted spreadsheet text.
    const safe = /^[\s]*[=+@-]/.test(cell) ? `'${cell}` : cell;
    return `"${safe.replaceAll('"', '""')}"`;
  }).join(",")).join("\n");
}

function download(name: string, body: string, type: string): void {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Findings({ findings }: { findings: Finding[] }) {
  return <ul className="prince-findings">{findings.map((finding, index) => <li key={index}>
    <strong>{finding.severity} · {finding.code}</strong>
    <p>{finding.message}</p>
  </li>)}</ul>;
}

export default function PrinceApp() {
  const [apiBase, setApiBase] = useState(API_DEFAULT);
  const [pdbId, setPdbId] = useState("6F5J");
  const [structureText, setStructureText] = useState("");
  const [filename, setFilename] = useState("");
  const [chain, setChain] = useState("C");
  const [assembly, setAssembly] = useState("1");
  const [profile, setProfile] = useState<Profile>("antibody_epitope");
  const [top, setTop] = useState(5);
  const [hotspots, setHotspots] = useState("C405,C408");
  const [evidenceYaml, setEvidenceYaml] = useState("");
  const [ranking, setRanking] = useState("structural");
  const [sourceId, setSourceId] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState("Not checked");
  const [fileBusy, setFileBusy] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const structureRead = useRef(0);
  const evidenceRead = useRef(0);
  const hasExactlyOneTarget = Boolean(pdbId.trim()) !== Boolean(structureText.trim());
  const targetHint = hasExactlyOneTarget ? "" : "Provide exactly one PDB ID or structure file.";

  useEffect(() => { void checkHealth(); }, []);

  async function checkHealth() {
    setHealth("Checking…");
    try {
      const response = await fetch(`${apiBase.replace(/\/$/, "")}/api/health`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.service !== "PRINCE" || data.status !== "ok") throw new Error("Not a PRINCE worker");
      setHealth("API online");
    } catch (cause) {
      setHealth("Worker offline");
    }
  }

  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (!hasExactlyOneTarget) { setError(targetHint); return; }
    if (!Number.isInteger(top) || top < 1 || top > 10) { setError("Choose 1 to 10 proposed sites."); return; }
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        chain: chain.trim() || undefined, assembly: assembly.trim() || undefined,
        profile, top, hotspots: hotspots.trim() || undefined,
        evidence_yaml: evidenceYaml.trim() || undefined,
        ...(ranking === "evidence" ? { ranking } : {}),
        ...(sourceText.trim() ? { source_documents: [{ source: sourceId.trim(), text: sourceText, chain: chain.trim() || undefined }] } : {}),
      };
      if (pdbId.trim()) payload.pdb_id = pdbId.trim();
      else { payload.structure_text = structureText; payload.filename = filename; }
      const serialized = JSON.stringify(payload);
      if (new TextEncoder().encode(serialized).byteLength > MAX_BYTES) {
        throw new Error("The complete JSON request exceeds 8 MiB. Use a smaller structure/evidence file or the CLI; JSON escaping also counts toward this limit.");
      }
      const response = await fetch(`${apiBase.replace(/\/$/, "")}/api/analyze`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: serialized,
        signal: AbortSignal.timeout(120000),
      });
      const body = await response.json();
      if (!response.ok || body.error) {
        throw new Error(`${body.error?.code ? `${body.error.code}: ` : ""}${body.error?.message ?? `HTTP ${response.status}`}`);
      }
      if (!body.target || !Array.isArray(body.proposal?.patches) || !Array.isArray(body.checks) || !body.validation) {
        throw new Error("The configured API returned an incompatible analysis record.");
      }
      setResult(body as AnalyzeResponse);
      setHealth("API online");
      window.setTimeout(() => document.getElementById("prince-results-heading")?.focus(), 50);
    } catch (cause) {
      setError(cause instanceof TypeError ? "Could not reach the analysis worker. Check Connection settings and start the local API using the quickstart guide." : cause instanceof Error ? cause.message : "Analysis failed");
    } finally { setBusy(false); }
  }

  async function fileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const token = ++structureRead.current;
    setFileBusy(false);
    setStructureText("");
    setFilename("");
    setPdbId("");
    setResult(null);
    if (!/\.(cif|mmcif|pdb)$/i.test(file.name) || file.size > MAX_BYTES) {
      setError("Choose a .cif, .mmcif or .pdb file smaller than 8 MiB. The complete JSON request must also fit within 8 MiB.");
      event.target.value = "";
      return;
    }
    setError(null);
    setFileBusy(true);
    try {
      const text = await file.text();
      if (token !== structureRead.current) return;
      setStructureText(text);
      setFilename(file.name);
    } catch {
      if (token === structureRead.current) setError("The selected structure could not be read.");
    } finally {
      if (token === structureRead.current) setFileBusy(false);
    }
  }

  async function evidenceSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const token = ++evidenceRead.current;
    setEvidenceYaml("");
    setEvidenceBusy(false);
    setResult(null);
    if (!/\.ya?ml$/i.test(file.name) || file.size > MAX_BYTES) {
      setError("Choose a YAML evidence table smaller than 8 MiB.");
      event.target.value = "";
      return;
    }
    setError(null);
    setEvidenceBusy(true);
    try {
      const text = await file.text();
      if (token === evidenceRead.current) setEvidenceYaml(text);
    } catch {
      if (token === evidenceRead.current) setError("The evidence table could not be read.");
    } finally {
      if (token === evidenceRead.current) setEvidenceBusy(false);
    }
  }

  return <section className="prince-app" aria-label="Structural analysis workspace">
    <div className="prince-console-head">
      <div className="bench-mode"><span className="mode-mark" aria-hidden="true">⊞</span><h2>Preflight</h2><span className="mode-description">Structure → sites → checks</span></div>
      <div className="prince-api-status">
        <span className={health === "API online" ? "status-dot online" : "status-dot"} aria-hidden="true" />
        <span role="status">{health === "API online" ? "Worker connected" : health}</span><button type="button" onClick={checkHealth}>Check connection</button>
      </div>
    </div>
    <div className="prince-workbench">
    <form className="prince-input-panel" onSubmit={analyze} onChange={() => setResult(null)}>
      <div className="panel-heading"><h3>Inputs</h3><span>PDB / mmCIF</span></div>
      <fieldset className="prince-form" disabled={busy}>
        <legend className="sr-only">Target and analysis settings</legend>
        <div className="form-step-heading"><h3>Target structure</h3></div>
        <div className="prince-target-grid">
          <label>PDB ID<input value={pdbId} onChange={(e) => {
            ++structureRead.current;
            setFileBusy(false);
            setPdbId(e.target.value);
            setStructureText("");
            setFilename("");
          }} placeholder="6F5J" spellCheck={false} autoCapitalize="characters" /></label>
          <label className="structure-upload">Or choose a file<input type="file" accept=".cif,.mmcif,.pdb" onChange={fileSelected} /></label>
        </div>
        <p className="prince-file-note">{fileBusy ? "Reading structure…" : filename ? `Loaded ${filename} (${structureText.length.toLocaleString()} characters)` : "PDB or mmCIF · 8 MiB total request limit"}</p>
        <div className="prince-controls">
          <label>Chain<input value={chain} onChange={(e) => setChain(e.target.value)} placeholder="C" /></label>
          <label>Assembly<input value={assembly} onChange={(e) => setAssembly(e.target.value)} placeholder="1" /></label>
        </div>
        <div className="prince-controls profile-controls">
          <label>Profile<select aria-label="Proposal profile" value={profile} onChange={(e) => setProfile(e.target.value as Profile)}>
            <option value="antibody_epitope">Antibody epitope · fitted</option>
            <option value="designability">Designability · unvalidated</option>
            <option value="exposure_only">Exposure only · baseline</option>
          </select></label>
          <label>Sites<input type="number" min={1} max={10} step={1} required value={Number.isNaN(top) ? "" : top} onChange={(e) => setTop(e.target.valueAsNumber)} /></label>
        </div>
        <p className="prince-help context-help">Use author chain IDs. Leave assembly blank if none applies.</p>
        <div className="form-step-heading"><h3>Selected hotspots</h3><span>Optional</span></div>
        <label><span className="sr-only">Optional hotspot check</span><input value={hotspots} onChange={(e) => setHotspots(e.target.value)} placeholder="C325,C326" />
          <span className="prince-help">Author residue IDs, separated by commas. Checked independently from proposed sites.</span></label>
        <div className="form-step-heading"><h3>Evidence</h3><span>Optional</span></div>
        <details className="prince-evidence-input">
          <summary>Reviewed evidence <span>YAML</span></summary>
          <p>Upload or paste a reviewed evidence table. Each qualifying row needs a source, review status, and reviewer attribution.</p>
          <label>Upload evidence table<input type="file" accept=".yaml,.yml" onChange={evidenceSelected} /></label>
          <label>Evidence YAML<textarea aria-label="Evidence YAML" rows={7} value={evidenceYaml} onChange={(e) => {
            ++evidenceRead.current;
            setEvidenceBusy(false);
            setEvidenceYaml(e.target.value);
          }} placeholder="rows: []" spellCheck={false} /></label>
          {evidenceBusy && <p role="status">Reading evidence locally…</p>}
          <label>Ranking policy<select aria-label="Ranking policy" value={ranking} onChange={(e) => setRanking(e.target.value)}>
            <option value="structural">Structural ranking; evidence only in checks</option>
            <option value="evidence">Reviewed experimental evidence first, then structure</option>
          </select></label>
          <p className="prince-help">Evidence-first ordering requires reviewed assay or mutagenesis coverage. It is uncalibrated; missing evidence is not negative evidence.</p>
        </details>
        <details className="prince-evidence-input">
          <summary>Source excerpts <span>TEXT</span></summary>
          <p>Collect verbatim residue-related sentences from a passage using local text rules. Each excerpt retains its citation and source position and requires review before use as evidence.</p>
          <label>Source DOI or PMID<input value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder="10.1073/pnas.1615695114 or PMID:28270616" /></label>
          <label>Source passage<textarea aria-label="Source passage" rows={6} value={sourceText} onChange={(e) => setSourceText(e.target.value)} spellCheck={false} /></label>
          <p className="prince-help">Use a passage you have permission to process. After analysis, download the excerpts, check the source and residue numbering, and upload the reviewed table above.</p>
        </details>
        <details className="prince-connection">
          <summary>Connection <span>API</span></summary>
          <label>API URL<input value={apiBase} onChange={(e) => { setApiBase(e.target.value); setHealth("Not checked"); }} inputMode="url" /></label>
          <p className="prince-help">Structures and passages are sent here when you run analysis. <a href="/guide/#setup">Local worker setup ↗</a></p>
        </details>
        {targetHint && <p className="prince-help">{targetHint}</p>}
        {error && <p className="prince-error" role="alert">{error}</p>}
        <button className="prince-submit" type="submit" disabled={busy || fileBusy || evidenceBusy || !hasExactlyOneTarget}>
          {busy ? "Running preflight…" : "Run preflight"}<span aria-hidden="true">{busy ? "◌" : "↗"}</span>
        </button>
        <p className="prince-submit-note" role="status">{busy ? "Reading coordinates and checking surface sites…" : "A GO is a structural check, not proof of binding."}</p>
      </fieldset>
    </form>
    <div className="prince-output-panel" aria-busy={busy}>
    <div className="panel-heading"><h3>Results</h3><span className={busy ? "run-state is-running" : "run-state"}>{busy ? "Running" : result ? "Complete" : error ? "Run failed" : "Not run"}</span></div>
    {!result && <div className="prince-empty">
      <div className="empty-structure" aria-hidden="true">
        <svg viewBox="0 0 520 330" fill="none">
          <defs><pattern id="bench-grid" width="26" height="26" patternUnits="userSpaceOnUse"><path d="M26 0H0V26" stroke="#e5ce94" strokeOpacity=".08" /></pattern><radialGradient id="bench-vignette"><stop stopColor="white"/><stop offset="1" stopColor="black"/></radialGradient><mask id="bench-grid-mask"><rect width="520" height="330" fill="url(#bench-vignette)"/></mask></defs>
          <rect width="520" height="330" fill="url(#bench-grid)" mask="url(#bench-grid-mask)" />
          <ellipse cx="260" cy="170" rx="160" ry="102" stroke="#e5d09a" strokeOpacity=".15" strokeDasharray="3 7" />
          <path d="M80 170h25m310 0h25M260 45v20m0 210v20" stroke="#e5d09a" strokeOpacity=".5" />
          {pdbId.trim().toUpperCase() === "6F5J" && !filename ? <g className={busy ? "specimen-trace is-running" : "specimen-trace"}>
            {protein.residues.map((residue, i) => {
              const previous = protein.residues[i - 1];
              const point = [(residue.p[0] - 103) * 2.5 + 260, (residue.p[2] - 90) * 2.5 + 170];
              if (!previous || Math.hypot(...residue.p.map((p, j) => p - previous.p[j])) > 5) return null;
              return <line key={residue.id} x1={(previous.p[0] - 103) * 2.5 + 260} y1={(previous.p[2] - 90) * 2.5 + 170} x2={point[0]} y2={point[1]} stroke="#e1ce9e" strokeWidth="1.2" strokeOpacity={.3 + i / protein.residues.length * .55} />;
            })}
          </g> : <g stroke="#e5d09a" strokeOpacity=".4"><path d="M240 150h40v40h-40zM250 170h20m-10-10v20" /></g>}
        </svg>
        {pdbId.trim().toUpperCase() === "6F5J" && !filename && <span className="empty-specimen-label">6F5J · CHAIN C · Cα REFERENCE</span>}
      </div>
      <div className="empty-copy"><span className="prince-eyebrow">{busy ? "ANALYSIS IN PROGRESS" : error ? "CHECK YOUR INPUTS" : "READY WHEN YOU ARE"}</span><h3>{busy ? "Checking the structure" : error ? "Analysis could not complete" : "No results yet"}</h3><p>{busy ? "Surface features, ranked patches, and independent hotspot checks will appear here." : error ? "The worker’s response is shown with your inputs. Update the target or connection and try again." : "Choose a structure and run preflight. Ranked sites and hotspot findings will appear here."}</p></div>
      <div className="empty-output-key"><span><i />Ranked sites</span><span><i />Hotspot checks</span><span><i />Source record</span></div>
      <details className="example-note"><summary>About the prefilled example <span>+</span></summary><p>6F5J, chain C, assembly 1. Selected residues C405 and C408 are absent from the resolved structure, so their independent check returns STOP.</p><a href="/guide/#first-run">Example walkthrough ↗</a></details>
    </div>}
    {result && <div className="prince-results" aria-live="polite">
      <div className="prince-result-head">
        <div><p className="prince-eyebrow">RUN RECORD / V{result.schema_version}</p>
          <h3 id="prince-results-heading" tabIndex={-1}>{result.target.id} · chain {result.target.chain || "—"} · assembly {result.target.assembly_id ?? "none"}</h3>
          <p>{result.target.chains.length} chains available. Profile: <strong>{result.proposal.weight_profile}</strong>. Scores are relative rankings, not binding probabilities.</p></div>
        <div className="prince-downloads">
          <button type="button" onClick={() => download("prince-run.json", JSON.stringify(result, null, 2), "application/json")}>Download JSON</button>
          <button type="button" onClick={() => download("prince-sites.csv", csvFromResult(result), "text/csv")}>Download CSV</button>
        </div>
      </div>
      {result.selected_check && <section className={`prince-selected ${result.selected_check.verdict.toLowerCase()}`} aria-labelledby="prince-selected-title">
        <h4 id="prince-selected-title">Selected hotspots <span className="prince-verdict">{result.selected_check.verdict}</span></h4>
        <p><code>{result.selected_check.site.keys.join(", ")}</code> — independent check</p>
        <Findings findings={result.selected_check.findings} />
      </section>}
      <h4>Proposed sites <span className="result-count">{result.proposal.patches.length}</span></h4>
      <p>Ordered by the selected ranking policy. Inspect the findings for each site.</p>
      {result.proposal.patches.length === 0 ? <p>No eligible surface patches were returned for this target.</p> :
        <div className="prince-table-wrap" role="region" aria-label="Ranked sites, horizontally scrollable" tabIndex={0}><table>
          <caption className="sr-only">Ranked PRINCE proposed sites with structural checks</caption>
          <thead><tr><th>Rank</th><th>Score</th><th>Residues</th><th>Relative SASA</th><th>Score contributions</th><th>Reviewed evidence</th><th>Check</th></tr></thead>
          <tbody>{result.proposal.patches.map((patch, index) => {
            const check = result.checks.find((item) => item.rank === index + 1)?.record;
            return <tr key={index}>
              <td>{index + 1}</td><td>{patch.score.toFixed(4)}</td>
              <td><code>{patch.residues.join(", ")}</code></td><td>{patch.mean_relative_sasa.toFixed(4)}</td>
              <td>{Object.entries(patch.components).map(([name, value]) => <span className="prince-component" key={name}>{name}: {value.toFixed(3)}</span>)}</td>
              <td>{patch.evidence?.sources.length ? <>
                <strong>Evidence score: {patch.evidence.score.toFixed(3)}</strong>
                <details><summary>Reviewed sources and residues</summary>
                  <p>Structural rank {patch.structural_rank ?? "—"}, score {patch.structural_score?.toFixed(4) ?? "—"}.</p>
                  <p>Supports: {patch.evidence.supported_residues.join(", ") || "none"}.</p>
                  <p>Refutes: {patch.evidence.refuted_residues.join(", ") || "none"}.</p>
                  {patch.evidence.conflicting_residues.length > 0 && <p>Conflicting: {patch.evidence.conflicting_residues.join(", ")}.</p>}
                  <p>Sources: {patch.evidence.sources.join("; ")}.</p>
                  <p>Reviewers: {patch.evidence.reviewers.join(", ")}.</p>
                </details>
              </> : "No reviewed experimental evidence"}</td>
              <td><span className={`prince-verdict ${(check?.verdict ?? "").toLowerCase()}`}>{check?.verdict ?? "Not checked"}</span>
                {check && <details><summary>{check.findings.length} findings and reasons</summary><Findings findings={check.findings} /></details>}
              </td>
            </tr>;
          })}</tbody>
        </table></div>}
      {result.evidence && <section className="prince-evidence-status">
        <h4>Evidence record</h4>
        <p>Status: <strong>{result.evidence.status.replaceAll("_", " ")}</strong>.</p>
        <p>Effect reported by the API: {result.evidence.affects}.</p>
        {result.evidence.extraction && <div>
          <h5>Source excerpts · review required</h5>
          <p>Method: {result.evidence.extraction.method}. Excerpts do not affect ranking until reviewed and uploaded as an attributed evidence table.</p>
          <button type="button" onClick={() => download("prince-unreviewed-drafts.yaml", JSON.stringify({ rows: result.evidence?.extraction?.drafts }, null, 2), "application/yaml")}>Export excerpts · YAML</button>
          {result.evidence.extraction.drafts.length === 0 && <p>No residue-related sentences were found in this passage.</p>}
          {result.evidence.extraction.drafts.map((draft, index) => <article className="prince-draft" key={index}>
            <p><strong>Unreviewed</strong> · {draft.source} · {draft.residues.join(", ")}</p>
            <blockquote>{draft.quote}</blockquote>
            <p>Source character span {draft.span_start}–{draft.span_end}. Human review required.</p>
            {Object.entries(draft).filter(([key]) => key.includes("sha256")).map(([key,value]) => <p className="prince-hash" key={key}>{key}: <code>{String(value)}</code></p>)}
          </article>)}
        </div>}
      </section>}
      <details className="prince-validation">
        <summary>Validation & limitations</summary>
        <p>{result.validation.model_type}. Status: {result.validation.status.replaceAll("_", " ")}.</p>
        {result.validation.split_instances && <p>The structural fit used {result.validation.split_instances.train} training interfaces; {result.validation.split_instances.val} were reserved for validation and {result.validation.split_instances.test} for testing{result.validation.split_clusters ? ` across ${result.validation.split_clusters.test} test identity components` : ""}.</p>}
        {result.validation.evaluation && <p>Test residue AUROC: {result.validation.evaluation.fitted.macro_auroc.toFixed(4)} for the fitted model versus {result.validation.evaluation.exposure_only.macro_auroc.toFixed(4)} for exposure alone. This does not establish superiority or a probability of successful binding. Fitted residue AUPRC: {result.validation.evaluation.fitted.macro_auprc.toFixed(4)}.</p>}
        <p>The packaged fit metadata describe residue-level validation. A separate completed 110-interface site evaluation measures patch selection: <a href="/prince/site-evaluation.json">site outcomes and definitions</a> and <a href="/prince/site-uncertainty.json">component-level uncertainty</a>. A missing patch metric in this API record means it is not packaged here, not that no measurement exists.</p>
        <ul>{result.validation.limitations?.map((limit) => <li key={limit}>{limit}</li>)}</ul>
      </details>
      <details><summary>Complete machine-readable record and provenance</summary><pre className="prince-json">{JSON.stringify(result, null, 2)}</pre></details>
    </div>}
    </div>
    </div>
  </section>;
}
