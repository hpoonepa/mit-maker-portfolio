# Chai-1: upstream license and legacy platform gate

This file documents two separate facts: Chai Discovery's upstream license, and the acknowledgement settings retained in this Paper Crane snapshot. The settings were not changed during portfolio preparation.

## Upstream releases used by this source

- The retained Dockerfile installs `chai_lab==0.5.1`. Its [versioned LICENSE](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/LICENSE) is Apache-2.0, with copyright 2024 Chai Discovery. The [v0.5.1 README](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/README.md) explicitly states that both code and model weights are under Apache-2.0.
- The active Modal image installs `chai_lab==0.6.1`. Its [versioned LICENSE](https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/LICENSE) is Apache-2.0. The [current upstream README](https://github.com/chaidiscovery/chai-lab#licence) also identifies Apache-2.0 for code and weights.

The earlier description of these releases as noncommercial-only was inaccurate. The upstream license texts govern their respective releases; Paper Crane's root MIT license does not replace them. These source pins do not identify hashes for every model file downloaded by an existing deployment.

## Settings retained in this snapshot

| Source | Observable setting |
|---|---|
| [manifest.json](manifest.json) | `licenseGate: true` plus an older noncommercial label. |
| [run.sh](run.sh) | Exits unless `PAPERCRANE_LICENSE_ACK=chai1`; applies to this retained container entrypoint. |
| [modal_app.py](modal_app.py) | Separate Modal inference path; it does not run the container entrypoint above. |

These are legacy application-policy settings. Their presence must not be presented as an upstream noncommercial restriction, and this document does not claim an independently verified per-run UI/API enforcement chain. Changing application policy or deployed behavior would be a separate functional change.

For research outputs, cite Chai Discovery's [Chai-1 technical report](https://doi.org/10.1101/2024.10.10.615955) and any additional upstream methods used by the run.
