# Command-line reference

Run `preflight --help` and a subcommand's `--help` for the authoritative option list.

## Check a chosen site

```sh
preflight check 6f5j --hotspots C405,C408
preflight check target.cif --hotspots A101,A102,A103 --json check.json --csv residues.csv
```

Residue specifications use author chain and residue numbering. Checks cover unresolved residues, numbering, burial in the biological assembly, and patch geometry. `GO`, `GO_WITH_WARNINGS`, and `STOP` map to exit codes 0, 1, and 2; invalid input maps to 3. Inspect the findings rather than treating any nonzero code as a crash.

## Propose candidate sites

```sh
preflight propose 1ubq --chain A --profile antibody_epitope --top 3
```

Profiles are `antibody_epitope`, `exposure_only`, and exploratory `designability`. The latter uses hand-set weights awaiting minibinder-outcome validation. Proposals use the small residue scorer; they do not call the saved XGBoost classifier.

## Combined analysis

```sh
preflight analyze 1ubq --chain A --top 3 --json analysis.json
```

Add `--hotspots` for an independent selected-site check. `--sources sources.json` accepts source documents for draft extraction; `--evidence reviewed.yaml --ranking evidence` uses eligible reviewed evidence. A source document is an object with `source`, `text`, and optional `chain`. Drafts require review before becoming evidence rows.

## Serve the browser workspace

```sh
preflight serve --port 18766 \
  --allow-origin http://127.0.0.1:4330 \
  --allow-origin http://localhost:4330
```

See [api.md](api.md) for the JSON contract and request limits.

## Run the saved patch classifier

```sh
prince-rank --describe
prince-rank examples/patches.json --top 3 --output ranked.json
```

This accepts prepared features with explicit column names and the frozen PCA identifier. It returns stable diverse ranks, residue lists, scores, and the model SHA-256. See the repository README for the complete feature contract.

## Cache and standards

`HOTSPOT_PREFLIGHT_CACHE` chooses the runtime coordinate cache directory; the default is `.cache` in the current working directory. Research data uses a different variable, `PRINCE_DATA_DIR`.

The optional `sbol` extra supports SBOL3 constructs and annotations. `hotspot-preflight.cwl` defines a CWL command wrapper for `preflight check`, including explicit verdict exit codes. The installed JSON run-record schema is in `src/hotspot_preflight/schema/`.
