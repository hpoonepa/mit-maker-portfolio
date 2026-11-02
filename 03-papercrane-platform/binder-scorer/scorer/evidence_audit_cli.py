"""Local, dependency-free report export: python -m scorer.evidence_audit_cli."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from html import escape
from pathlib import Path

from scorer.evidence_audit import build_audit, canonical_json


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def load_input(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def _csv_cell(value: object) -> object:
    # Prevent spreadsheet formulas from user-supplied identifiers and origins.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_csv(report: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["candidate_id", "origin", "provenance", "status", "observed_methods",
                     "total_methods", "rank_best", "rank_worst", "blocked_reasons"])
    for candidate in report["candidates"]:
        envelope = candidate["rank_envelope"] or {}
        writer.writerow([_csv_cell(v) for v in [
            candidate["id"], candidate["origin"], candidate["provenance"], candidate["status"],
            candidate["observed_methods"], candidate["total_methods"],
            envelope.get("best", ""), envelope.get("worst", ""),
            "; ".join(candidate["blocked_reasons"]),
        ]])
    return output.getvalue()


def render_html(report: dict) -> str:
    def e(value: object) -> str:
        return escape(str(value), quote=True)

    def interval(value: dict | None) -> str:
        if not value:
            return "—"
        return str(value["best"]) if value["best"] == value["worst"] else f'{value["best"]}–{value["worst"]}'

    summary = report["summary"]
    method_headings = "".join(f'<th scope="col">{e(m["id"])}</th>' for m in report["methods"])
    rows = []
    for candidate in report["candidates"]:
        cells = []
        for method in report["methods"]:
            observation = candidate["scores"][method["id"]]
            if observation["status"] == "observed":
                rank = interval(candidate["rank_intervals"].get(method["id"]))
                label = f'{observation["value"]:g} · rank {rank}'
            else:
                label = f'{observation["status"]}: {observation["reason"]}'
            cells.append(f"<td>{e(label)}</td>")
        rows.append(
            f'<tr><th scope="row">{e(candidate["id"])}</th><td>{e(candidate["origin"])}</td>'
            f'<td>{e(candidate["provenance"])}</td><td>{e(candidate["status"].replace("_", " "))}</td>'
            f'<td>{candidate["observed_methods"]}/{candidate["total_methods"]}</td>'
            f'<td>{interval(candidate["rank_envelope"])}</td>{"".join(cells)}</tr>'
        )
    method_rows = "".join(
        f'<tr><th scope="row">{e(m["id"])}</th><td>{e(m["producer"])}</td><td>{e(m["version"])}</td>'
        f'<td>{e(m["evidence_family"])}</td><td>{"Higher" if m["higher_is_better"] else "Lower"}</td>'
        f'<td>{e(m["units"])}</td><td><code>{e(json.dumps(m["settings"], sort_keys=True))}</code></td></tr>'
        for m in report["methods"]
    )
    agreement_rows = "".join(
        f'<tr><th scope="row">{e(a["left"])} / {e(a["right"])}</th>'
        f'<td>{"Yes" if a["same_evidence_family"] else "No"}</td>'
        f'<td>{e(a["top_k_jaccard"] if a["top_k_jaccard"] is not None else a["unavailable_reason"])}</td></tr>'
        for a in report["method_agreement"]
    )
    warnings = "".join(f"<li>{e(w)}</li>" for w in report["warnings"])
    origin_rows = "".join(
        f'<tr><th scope="row">{e(group["origin"])}</th><td>{group["total_candidates"]}</td>'
        f'<td>{group["comparable_candidates"]}</td>' + "".join(
            f'<td>{group["observation_counts"][m["id"]]["observed"]}/{group["total_candidates"]} observed</td>'
            for m in report["methods"]
        ) + '</tr>' for group in report["coverage_by_origin"]
    )
    interpretation = "".join(f"<li>{e(item)}</li>" for item in report["interpretation"])
    kind = "Synthetic demonstration" if report["data_kind"] == "synthetic_demo" else "Research evidence audit"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{e(report["campaign_id"])} · Evidence audit</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #183135; background: #f4f6f3; }}
body {{ margin: 0; padding: 40px 5vw 64px; line-height: 1.55; }}
main {{ max-width: 1450px; margin: auto; }}
h1 {{ font-size: clamp(2rem, 4vw, 3.3rem); line-height: 1.1; margin: 12px 0; }}
h2 {{ margin-top: 36px; }} .eyebrow {{ color: #365f5c; letter-spacing: .08em; text-transform: uppercase; }}
.summary {{ display: flex; flex-wrap: wrap; gap: 20px; margin: 26px 0; }}
.card {{ background: white; padding: 18px 24px; border: 1px solid #ccd9d5; border-radius: 10px; }}
.card strong {{ display: block; font-size: 2rem; }}
.notice {{ background: #fff4dc; border-left: 4px solid #966215; padding: 12px 20px; }}
.scroll {{ overflow-x: auto; background: white; border: 1px solid #ccd9d5; border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; text-align: left; font-size: .9rem; }}
th, td {{ padding: 12px 16px; border-bottom: 1px solid #dbe3df; vertical-align: top; }}
thead {{ background: #e5eeea; }} code {{ overflow-wrap: anywhere; }}
.muted {{ color: #46615f; }} footer {{ margin-top: 32px; font-size: .85rem; overflow-wrap: anywhere; }}
@media print {{ body {{ padding: 10px; background: white; }} .scroll {{ overflow: visible; }} }}
</style></head><body><main>
<div class="eyebrow">{kind} · v1</div><h1>{e(report["campaign_id"])}</h1>
<p>How consistently do supplied methods order the same candidates?</p>
<div class="summary"><div class="card"><strong>{summary["total_candidates"]}</strong>Candidates supplied</div>
<div class="card"><strong>{summary["comparable_candidates"]}</strong>Common evidence cohort</div>
<div class="card"><strong>{summary["excluded_candidates"]}</strong>Outside comparison</div>
<div class="card"><strong>{summary["declared_evidence_families"]}</strong>Declared evidence families</div></div>
<div class="notice"><strong>Report scope</strong><p>Agreement describes consistency among the supplied methods. Predictive accuracy requires outcome evaluation.</p><ul>{warnings}</ul></div>
<h2>Candidate evidence</h2><p class="muted">Requested top-k: {report["config"]["top_k"]}; effective cutoff: {report["config"]["effective_top_k"]}.
Rows are ordered by candidate ID. Ranks apply only to the common cohort. An envelope is the best–worst occupied rank across methods, including exact ties.</p>
<div class="scroll" role="region" aria-label="Candidate evidence table" tabindex="0"><table>
<thead><tr><th scope="col">Candidate</th><th scope="col">Origin</th><th scope="col">Provenance</th><th scope="col">Assessment</th>
<th scope="col">Observed</th><th scope="col">Rank envelope</th>{method_headings}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>Coverage by origin</h2><p class="muted">Compare source coverage to identify uneven exclusions from the common cohort.</p>
<div class="scroll"><table><thead><tr><th scope="col">Origin</th><th scope="col">Supplied</th><th scope="col">Comparable</th>{method_headings}</tr></thead><tbody>{origin_rows}</tbody></table></div>
<h2>Method agreement</h2><p class="muted">Jaccard overlap compares exact top-k sets on the common cohort. A tie at the cutoff makes this statistic unavailable.</p>
<div class="scroll"><table><thead><tr><th scope="col">Methods</th><th scope="col">Shared family</th><th scope="col">Top-k overlap / unavailable reason</th></tr></thead><tbody>{agreement_rows}</tbody></table></div>
<h2>Evidence provenance</h2><div class="scroll"><table><thead><tr><th scope="col">Method</th><th scope="col">Producer</th><th scope="col">Version</th>
<th scope="col">Family</th><th scope="col">Better direction</th><th scope="col">Units</th><th scope="col">Settings</th></tr></thead><tbody>{method_rows}</tbody></table></div>
<h2>How to read the report</h2><ul>{interpretation}</ul>
<footer>Schema: {e(report["schema_version"])}<br>Canonical input SHA-256: <code>{report["input_sha256"]}</code><br>
This portable report loads no scripts, fonts, images, or external services. Machine-readable evidence is in report.json.</footer>
</main></body></html>'''


def export_bundle(report: dict, destination: Path) -> None:
    """Write to a fresh directory. Refuse to overwrite any existing report."""
    artifacts = {"report.json": canonical_json(report), "report.html": render_html(report),
                 "candidates.csv": render_csv(report)}
    manifest = {
        "schema_version": "evidence-audit-bundle.v1", "report_version": report["schema_version"],
        "input_sha256": report["input_sha256"], "config": report["config"],
        "artifacts": {name: hashlib.sha256(content.encode("utf-8")).hexdigest()
                      for name, content in artifacts.items()},
    }
    artifacts["manifest.json"] = canonical_json(manifest)
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in artifacts.items():
        (destination / name).write_bytes(content.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit supplied ranking evidence and export a portable report.")
    parser.add_argument("input", type=Path, help="Versioned evidence JSON file")
    parser.add_argument("--top-k", type=int, default=10, help="Shortlist cutoff (default: 10)")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing directories are never overwritten")
    args = parser.parse_args(argv)
    try:
        report = build_audit(load_input(args.input), top_k=args.top_k)
        export_bundle(report, args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"Evidence audit failed: {exc}", file=sys.stderr)
        return 2
    print(f"Audited {report['summary']['comparable_candidates']}/{report['summary']['total_candidates']} comparable candidates.")
    print(f"Report: {(args.output_dir / 'report.html').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
