# Paper Crane — Tool Integration Layer Plan

## 1. Tool Abstraction Interface

Every tool — open-source or frontier — implements a single contract: `ToolAdapter`. The adapter takes a normalized `DesignRequest` and returns a normalized `DesignResult`. This means the core platform never knows whether it's calling RFdiffusion locally or a licensed IsoMorphic-style API over HTTPS.

```ts
interface ToolAdapter {
  manifest: ToolManifest;
  validate(req: DesignRequest): ValidationError[];
  prepare(req: DesignRequest, workdir: string): Promise<PreparedJob>;
  run(job: PreparedJob): Promise<RawOutput>;
  parse(raw: RawOutput): DesignResult;
}

interface DesignRequest {
  targetPdb: string;             // S3 URI
  hotspots?: Residue[];          // normalized {chain, resi}
  seeds: number[];
  numDesigns: number;
  constraints?: {
    lengthRange?: [number, number];
    disulfides?: boolean;
    solubility?: 'strict' | 'default';
  };
  toolParams?: Record<string, unknown>;  // tool-specific escape hatch
}

interface DesignResult {
  designs: Array<{
    structurePath: string;     // S3 URI to PDB/CIF
    sequence: string;
    metrics: Record<string, number>;
    seed: number;
  }>;
  runMetadata: RunMetadata;
}
```

The `toolParams` escape hatch lets power users pass through tool-native flags without us building a GUI for every knob.

## 2. Containerization Strategy

- **Registry**: GitHub Container Registry (GHCR) — free for public images, tight GitHub Actions integration, no AWS lock-in during pre-seed. Migrate to ECR only if egress costs bite post-YC.
- **Naming convention**: `ghcr.io/papercrane/<tool>:<tool-version>-cuda<cuda>-<adapter-version>` e.g. `ghcr.io/papercrane/rfdiffusion:1.1.0-cuda12.1-a3`. The adapter version bumps when our wrapper changes without the tool changing.
- **Base images**: two shared bases — `papercrane/base-cuda12:latest` (PyTorch 2.3 + CUDA 12.1 + common bio libs) and `papercrane/base-cpu:latest`. Each tool Dockerfile starts `FROM` one of these, cutting 4-6 GB per image and halving build time.
- **Build pipeline**: GitHub Actions matrix builds each tool on tag push. Trivy scan + smoke test (run a 30-second fixture job) gates the push.

## 3. Runtime Execution Model

Every container follows the same contract — enforced by CI:

- Entrypoint: `/opt/papercrane/run.sh`
- Reads `/inputs/request.json` and `/inputs/target.pdb`
- Writes `/outputs/designs/*.pdb` and `/outputs/result.json`
- Logs to stdout (captured by the runner), errors exit non-zero with structured JSON on stderr

The runner (part of the scheduler plan 03, but our contract):
1. Pulls the pinned image digest (`sha256:...`, not a tag — for reproducibility).
2. Stages inputs: downloads target PDB from S3 → mounts to `/inputs` read-only.
3. Launches container with GPU request from the manifest.
4. Streams stdout to CloudWatch / our jobs DB; enforces timeout from manifest (hard kill at 1.5×).
5. On exit, syncs `/outputs/` → `s3://papercrane-jobs/<jobId>/` and emits a `RawOutput` event.

CPU/memory limits are set from the manifest. GPUs are requested via `--gpus` + MIG slicing where the scheduler allows.

## 4. Adapter Pattern for Tool Quirks

Adapters live **outside** upstream repos — we never fork. We vendor upstream as a git submodule inside our Docker image and wrap it with a thin Python CLI.

**BindCraft adapter stub** (`tools/bindcraft/adapter.py`):

```python
from papercrane.sdk import Adapter, DesignRequest, DesignResult
import subprocess, json, pathlib

class BindCraftAdapter(Adapter):
    manifest_path = "tools/bindcraft/manifest.json"

    def prepare(self, req: DesignRequest, workdir: pathlib.Path):
        cfg = {
            "target_pdb": "/inputs/target.pdb",
            "target_chain": req.target_chain or "A",
            "hotspots": [f"{h.chain}{h.resi}" for h in (req.hotspots or [])],
            "binder_length_range": req.constraints.length_range or [60, 150],
            "num_designs": req.num_designs,
            "seeds": req.seeds,
        }
        (workdir / "bindcraft.json").write_text(json.dumps(cfg))
        return {"cfg": str(workdir / "bindcraft.json")}

    def run(self, job):
        subprocess.run(
            ["python", "/opt/bindcraft/bindcraft.py",
             "--config", job["cfg"], "--out", "/outputs/designs"],
            check=True,
        )
        return {"out_dir": "/outputs/designs"}

    def parse(self, raw) -> DesignResult:
        designs = []
        for pdb in pathlib.Path(raw["out_dir"]).glob("*.pdb"):
            meta = json.loads(pdb.with_suffix(".json").read_text())
            designs.append({
                "structure_path": str(pdb),
                "sequence": meta["sequence"],
                "metrics": {
                    "iptm": meta["iptm"], "plddt": meta["plddt"],
                    "i_pae": meta["i_pae"], "hotspot_contact": meta["hs_contact"],
                },
                "seed": meta["seed"],
            })
        return DesignResult(designs=designs, run_metadata={"tool": "bindcraft"})
```

**RFdiffusion adapter** is simpler — it only outputs backbones, so the adapter pipes designs into ProteinMPNN automatically (composed internally) unless the caller opts out via `toolParams.skip_mpnn=true`. That composition is also reusable: any tool producing backbones can chain into an `mpnn_sequence_design` step.

## 5. Output Parsing + Metric Computation

We split metric computation from tool execution. Every tool's raw output (PDB/CIF + whatever metrics the tool emits natively) lands in S3, then a **validator image** (`papercrane/validator:latest`) runs as a second stage per design and computes our canonical metric suite: ipSAE, DockQ, pTMEnergy, LIS, Overath, hotspot contact fraction, ESM2 pLL. This means:
- Metrics stay consistent when we swap tool versions.
- We can re-score historical jobs when we add a new metric without re-running expensive design.
- Tools don't need to bundle our validator.

Validator runs on a smaller GPU (A10/T4) in parallel across designs.

## 6. Tool Catalog + Discovery

A `tools` Postgres table is the source of truth, seeded from a checked-in `tools.manifest.json` at build time:

**ToolManifest JSON schema sample:**

```json
{
  "id": "bindcraft",
  "displayName": "BindCraft",
  "version": "1.2.0",
  "adapterVersion": "a3",
  "category": "binder_design",
  "tier": "open",
  "license": "MIT",
  "image": "ghcr.io/papercrane/bindcraft:1.2.0-cuda12.1-a3",
  "imageDigest": "sha256:8f2e...",
  "compute": {
    "gpu": "A100-40GB", "gpuCount": 1,
    "cpuCores": 8, "memoryGb": 32,
    "estSecondsPerDesign": 140
  },
  "inputSchema": "schemas/bindcraft.input.json",
  "outputSchema": "schemas/common.output.json",
  "defaultParams": { "binder_length_range": [60, 150] },
  "composes": ["proteinmpnn"]
}
```

The frontend queries `/api/tools` and renders cards dynamically — adding a new tool does not require UI code changes.

## 7. Versioning & Reproducibility

Every job row stores: image digest, adapter version, seed list, input hash (SHA256 of normalized request), environment hash (CUDA + driver), git SHA of the adapter repo. Old jobs always remain reproducible because digests are immutable. Tool upgrades are additive — a new `bindcraft:1.3.0-a4` appears as a selectable version; old jobs keep pointing at `1.2.0-a3`. Deprecation policy: minor versions hidden from UI after 90 days but still runnable via API.

## 8. GPU/CPU Profiles — Tool Catalog

| Tool | Category | Tier | GPU | VRAM | ~s/design | License |
|---|---|---|---|---|---|---|
| RFdiffusion | backbone | open | A100 | 24 GB | 35 | BSD-3 |
| ProteinMPNN | sequence | open | A10 | 10 GB | 4 | MIT |
| LigandMPNN | sequence (lig) | open | A10 | 12 GB | 6 | MIT |
| SolubleMPNN | sequence (sol) | open | A10 | 10 GB | 5 | MIT |
| BindCraft | end-to-end | open | A100 | 40 GB | 140 | MIT |
| Chroma | generative | open | A100 | 24 GB | 50 | Apache-2 |
| BoltzGen | binder gen | open | A100 | 40 GB | 90 | MIT |
| ESM2 (650M) | embed/score | open | A10 | 12 GB | 1 | MIT |
| Boltz-1 | structure | open | A100 | 40 GB | 70 | MIT |
| Boltz-2 | structure | open | A100 | 80 GB | 110 | MIT |
| Chai-1 | structure | open-weights | A100 | 80 GB | 130 | non-commercial |
| AlphaFold 3 | structure | frontier | H100 | 80 GB | 180 | API/licensed |

Tier `frontier` tools are gated behind paid plans; `open-weights` with non-commercial licenses (Chai-1) are gated behind a user-acknowledged EULA checkbox.

## 9. Frontier Tool Integration

Closed-weight models get a different adapter base class — `RemoteAdapter` — which calls an HTTPS endpoint instead of spawning a container. The contract is identical from the platform's view; only `run()` differs. Auth tokens live in AWS Secrets Manager, pulled per-call. Rate limits and per-user quotas are enforced in the adapter. This means adding AlphaFold 3 (or a hypothetical IsoMorphic endpoint) is purely a matter of writing one `RemoteAdapter` subclass plus a manifest — no core code changes, no container build. Tier gating is a simple check on `manifest.tier` in the job submission API.

## 10. Playbook — Adding Tool #13 (<4 hours)

1. `papercrane-cli scaffold-tool mynewtool` — generates `tools/mynewtool/` with Dockerfile, manifest, adapter stub, fixture test (15 min).
2. Fill `Dockerfile`: `FROM ghcr.io/papercrane/base-cuda12` + upstream install (30 min).
3. Implement `prepare/run/parse` in `adapter.py` (60-90 min).
4. Drop a target PDB in `tests/fixtures/` and run `pytest tools/mynewtool` (30 min).
5. Push branch → GitHub Actions builds, scans, smoke-tests, pushes to GHCR (20 min, mostly wait).
6. PR merge auto-appends to `tools.manifest.json`; frontend picks it up on next deploy (5 min).

## 11. Build Sequence — 6 Milestones

1. **M1 (week 1):** Define `ToolAdapter` SDK + base images + GHCR + one tool end-to-end (BindCraft). Job runs via CLI locally against local Docker.
2. **M2 (week 2):** Validator image with ipSAE + DockQ + pTMEnergy. Catalog table + `/api/tools` endpoint.
3. **M3 (week 3):** Add RFdiffusion + ProteinMPNN + Boltz-2. Compose RFdiffusion → ProteinMPNN chain.
4. **M4 (week 4):** Add Chai-1 + BoltzGen + LigandMPNN + SolubleMPNN + ESM2 + Boltz-1 + Chroma. 11 tools in catalog.
5. **M5 (week 5):** `RemoteAdapter` + AlphaFold 3 wired in, tier gating enforced. Scaffold CLI published.
6. **M6 (week 6):** Reproducibility audit — replay 20 historic jobs against current digests, document version policy, open-source the SDK repo to seed community adapters.

## 12. Risks + Mitigations

- **Upstream drift** — tools change arg names or output formats between versions. Mitigation: adapters pinned to exact tool git SHAs; CI smoke tests catch breakage before promotion.
- **License creep** on closed-weight tools (Chai non-commercial, AF3 API terms). Mitigation: `tier` + `license` fields in manifest, EULA gate in UI, legal review before any tool marked `tier=frontier` goes live.
- **Image bloat** — CUDA + PyTorch + weights easily hit 20 GB/image. Mitigation: shared bases, multi-stage builds, model weights mounted from S3-backed volume instead of baked in where possible.
- **Version drift between prod and user local reproduction** — always report image digest, adapter SHA, and a one-click `papercrane reproduce <jobId>` that pulls the exact digest.
- **Two-person scaling** — the scaffold CLI + validator split are explicit moves to make tool #13 a community contribution, not a founder task.

Relevant file path: `/Users/harsha/Desktop/claudeprojects/mosaic/papercrane/` (existing webapp — integration layer to live alongside as `/papercrane/tools-sdk/` once built).
