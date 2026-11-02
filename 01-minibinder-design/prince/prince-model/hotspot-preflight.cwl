#!/usr/bin/env cwl-runner
#
# Common Workflow Language description of `preflight check`.
#
# cwlVersion is v1.2 deliberately: v1.2.0 is the current stable CWL release.
# A v1.3 exists only as the pre-release v1.3.0-dev1, so targeting it would make
# this document depend on an unreleased specification.
#
# Validate with:  cwltool --validate hotspot-preflight.cwl
# (enforced in CI by the `cwl-validate` job in .gitlab-ci.yml)
#
# ---------------------------------------------------------------------------
# EXIT CODE MAPPING — READ THIS BEFORE CHANGING IT
# ---------------------------------------------------------------------------
# `preflight check` uses the exit code to carry the verdict:
#
#     0  GO                 the chosen hotspots survived every check
#     1  GO_WITH_WARNINGS   usable, but at least one check raised a WARN
#     2  STOP               at least one check returned KILL
#     3  usage error        bad arguments, unreadable structure, etc.
#
# CWL treats ANY non-zero exit code as a failure unless told otherwise. If
# `successCodes` is left at its default, a GO_WITH_WARNINGS run (exit 1) is
# indistinguishable from a crash, and a CWL workflow would abort on a result
# that is in fact a usable, merely-caveated verdict. The mapping below is
# therefore explicit and must stay explicit.
#
# `temporaryFailCodes` is declared empty on purpose. Every non-zero code in
# this scheme is a deterministic statement about the input, so nothing here is
# worth a retry: re-running an exit 2 on the same structure returns exit 2.
# Declaring the empty list documents that decision rather than leaving a reader
# to wonder whether it was forgotten.
# ---------------------------------------------------------------------------

cwlVersion: v1.2
class: CommandLineTool
id: hotspot-preflight-check
label: hotspot-preflight check
doc: |
  Validate a user-chosen set of binder-design hotspot residues against a target
  structure. Reports, per residue, whether it is resolved in the deposited
  coordinates, whether it remains solvent-exposed on the biological assembly,
  and whether the residue identifier resolves in the expected numbering scheme.

  Intended to run immediately before a binder design job (BindCraft,
  RFdiffusion, BoltzGen), all of which accept hotspot residues as unvalidated
  user input.

$namespaces:
  edam: http://edamontology.org/

requirements:
  # Needed so that the optional output globs can evaluate to an empty list when
  # the corresponding output path was not requested. Without this, a null glob
  # is an error rather than "no file".
  InlineJavascriptRequirement: {}

baseCommand: [preflight, check]

inputs:
  structure:
    type: File
    label: Target structure
    doc: |
      Target structure in mmCIF (preferred) or legacy PDB format. mmCIF is
      preferred because the numbering and biological-assembly checks rely on
      categories that have no PDB-format equivalent.
    format:
      - edam:format_1477  # mmCIF
      - edam:format_1476  # PDB
    inputBinding:
      position: 1

  hotspots:
    type: string
    label: Hotspot residue list
    doc: |
      Comma-separated hotspot residues as chain + author residue number, e.g.
      "C405,C408". These are the residues whose reality is being checked.
    inputBinding:
      prefix: --hotspots

  crop:
    type: string?
    label: Construct crop range
    doc: |
      Optional residue range describing the truncated construct the designer
      actually intends to express, e.g. "C:310-398". Supplying it enables the
      crop-artifact comparison, which flags residues that look exposed only
      because the crop removed whatever was burying them.
    inputBinding:
      prefix: --crop

  json_out:
    type: string?
    label: JSON run-record filename
    doc: |
      Optional filename for the machine-readable run record (input hashes,
      thresholds, pinned SASA parameters, per-residue findings, verdict).
    inputBinding:
      prefix: --json

  csv_out:
    type: string?
    label: CSV per-residue table filename
    doc: Optional filename for the per-residue findings table as CSV.
    inputBinding:
      prefix: --csv

  assembly:
    type: string?
    label: Biological assembly to measure burial on
    doc: |
      Name of the biological assembly to expand before computing solvent
      accessibility. Defaults to the first assembly declared in the file.
      Worth setting explicitly in a workflow, because the default is a property
      of the deposition rather than of your intent.
    inputBinding:
      prefix: --assembly

  quiet:
    type: boolean?
    label: Suppress the human-readable report
    doc: |
      Suppress the stdout report. The exit code and any requested output files
      are still produced, so this is safe in a pipeline that reads the JSON run
      record rather than the prose.
    inputBinding:
      prefix: --quiet

outputs:
  run_record:
    type: File?
    label: JSON run record
    doc: Present only when `json_out` was supplied.
    format: edam:format_3464  # JSON
    outputBinding:
      glob: "$(inputs.json_out === null ? [] : [inputs.json_out])"

  residue_table:
    type: File?
    label: Per-residue findings table
    doc: Present only when `csv_out` was supplied.
    format: edam:format_3752  # CSV
    outputBinding:
      glob: "$(inputs.csv_out === null ? [] : [inputs.csv_out])"

  report:
    type: stdout
    label: Human-readable verdict report
    doc: |
      The rendered verdict and per-residue kill/warn reasons as written to
      stdout. Always produced, including on a STOP verdict, because the reasons
      are the point of a STOP.

stdout: preflight-report.txt

# See the EXIT CODE MAPPING block at the top of this file.
successCodes: [0, 1]         # GO, GO_WITH_WARNINGS
temporaryFailCodes: []       # nothing in this scheme is retryable
permanentFailCodes: [2, 3]   # STOP, usage error
