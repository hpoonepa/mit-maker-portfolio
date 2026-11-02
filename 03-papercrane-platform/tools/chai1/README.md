# Chai-1 — Paper Crane integration

This integration runs [Chai Discovery's Chai-1](https://github.com/chaidiscovery/chai-lab) for molecular structure prediction. Paper Crane supplies job/input translation and result handling; Chai Discovery supplies the model and upstream software.

## Versions and execution paths

| Path | Package pin | Behavior |
|---|---|---|
| Active [Modal app](modal_app.py) | `chai_lab==0.6.1` | Builds a tool-specific image, initializes model files, runs inference on an `A100-80GB` by default, and returns structure bytes plus available confidence metrics. Image initialization and live jobs use remote GPU compute. |
| Retained [Dockerfile](Dockerfile), [adapter.py](adapter.py), [run.sh](run.sh) | `chai_lab==0.5.1` | Container adapter reads `/inputs/request.json`, produces structures/metrics under `/outputs`, and requires the existing `PAPERCRANE_LICENSE_ACK=chai1` environment guard. `CHAI1_SHA` remains an unresolved placeholder. |

The catalog's `version: 1.0.0` is a historical integration label; package pins are listed above. The active worker dispatch uses Modal app `chai1` / `papercrane_dispatch`. The container recipe is retained as source; a deployed image digest and a current end-to-end run still need verification.

## Upstream license and retained platform policy

The pinned [v0.5.1 LICENSE](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/LICENSE) is Apache-2.0, and its [versioned README](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/README.md) explicitly applies Apache-2.0 to code and model weights. The Modal pin also has a [v0.6.1 Apache license](https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/LICENSE); the [current upstream README](https://github.com/chaidiscovery/chai-lab#licence) makes the same code-and-weights statement. Upstream copyright is 2024 Chai Discovery.

Paper Crane's manifest still contains a legacy noncommercial label and `licenseGate: true`; the retained container entrypoint still requires acknowledgement. These legacy platform settings remain unchanged. The cited releases use Apache-2.0; enforcement of the platform acknowledgement is specific to each transport and requires separate verification. See [LICENSE-GATE.md](LICENSE-GATE.md).

## Inputs, outputs and tests

[schemas/input.json](schemas/input.json) describes chains, parameters and seeds; [schemas/output.json](schemas/output.json) describes normalized predictions. Optional `binderChainId` scopes binder metrics. The adapter records structure predictions and available confidence measures; experimental binding measurements remain separate.

Fixture tests live in `tests/`; `test_modal_cofold.py` covers the Modal input contract. The root `pnpm modal:check` performs a source/entrypoint dry-run. Running the Modal app, building its model-initialized image or running a full integration job requires real compute and model files.

## Scientific citation

Chai Discovery (2024), *Chai-1: Decoding the molecular interactions of life*, [doi:10.1101/2024.10.10.615955](https://doi.org/10.1101/2024.10.10.615955). If an analysis also uses automatic ColabFold/MMseqs2 MSA generation, retain the additional citations requested by the [versioned upstream README](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/README.md). Further software credits are in [THIRD_PARTY/CITATIONS.md](../../THIRD_PARTY/CITATIONS.md).
