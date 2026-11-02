# Local analysis API

The worker is provided by `hotspot_preflight.server` in the model repository. Start it with `preflight serve --port 18766 --allow-origin http://127.0.0.1:4330`.

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | Status, service name, and schema version |
| GET | `/api/validation` | Installed residue-model metadata, excluding split identifier lists |
| POST | `/api/analyze` | Ranked proposals, individual checks, optional selected-hotspot check, and evidence drafts |

```sh
curl http://127.0.0.1:18766/api/health
curl http://127.0.0.1:18766/api/analyze \
  -H 'Content-Type: application/json' \
  --data '{"pdb_id":"1ubq","chain":"A","top":3}'
```

## Request fields

Supply exactly one of `pdb_id` and `structure_text`. Unknown fields are rejected.

| Field | Type | Meaning |
|---|---|---|
| `pdb_id` | string | Four-character PDB identifier |
| `structure_text` | string | Uploaded coordinate text |
| `filename` | string | Upload basename ending in `.cif`, `.mmcif`, or `.pdb`; defaults to `upload.cif` |
| `chain` | string | Author chain identifier; omission lets the proposal code select a chain |
| `assembly` | string | Assembly identifier; omit to use normal assembly selection |
| `profile` | string | `antibody_epitope` (default), `exposure_only`, or exploratory `designability` |
| `top` | integer | 1–10, default 3 |
| `hotspots` | string | Optional independent check, e.g. `C405,C408` |
| `evidence_yaml` | string | Attributed, reviewed evidence table |
| `source_documents` | array | Objects containing `source`, `text`, and optional `chain` for draft extraction |
| `ranking` | string | `structural` (default) or `evidence` |

Evidence extracted from source documents remains a draft. Only eligible reviewed experimental rows can affect evidence-based ordering. The predictive benefit of that ordering has not been established.

## Response fields

`schema_version` identifies the JSON contract. `target` records the target, chain, and assembly. `proposal.patches` contains the ranked sites. `checks` contains their structural checks. `selected_check` is a separate record for supplied hotspots or `null`. `validation` describes the residue baseline, and `evidence` records review and extraction status.

Read `selected_check.verdict` independently of proposed-site verdicts. Scores are target-relative rankings. Neither `GO` nor a high score means experimentally validated binding.

## Limits and errors

The complete JSON request is limited to **8 MiB**; uploaded coordinate text must fit within that limit. Structures must contain one model and no more than 100,000 atoms. For larger or multi-model work, use the structural CLI's supported model-selection workflow.

| Status | Meaning |
|---|---|
| 400 | Invalid payload, coordinate data, or analysis settings |
| 403 | Host or browser origin rejected |
| 404 | Unknown endpoint |
| 415 | Content type is not `application/json` |
| 502 | Structure retrieval or temporary storage failed |

Errors use `{"error":{"code":"...","message":"..."}}`. The worker binds to loopback and is a single-process local research service. It is not a public job queue. Requests use an exact origin allowlist and must address `localhost` or `127.0.0.1` at the configured port.
