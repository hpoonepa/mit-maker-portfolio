# Protenix in the `alphafold3` catalog slot

Paper Crane's active path for this catalog identifier runs [ByteDance Protenix](https://github.com/bytedance/Protenix) on Modal. Protenix is a separate open-source implementation of AlphaFold 3-style inference. The configured service is Paper Crane's Modal deployment of Protenix.

## Active Modal implementation

[modal_app.py](modal_app.py) installs `protenix==1.0.4` and defaults to the `protenix_mini_default_v0.5.0` model. The package version and model checkpoint name are different identifiers. The default inference GPU is `L40S`; the image's model-initialization step requests `A10G`. Both image initialization and live inference require configured Modal compute and can incur cost.

The [manifest](manifest.json) selects Modal app `alphafold3`, function `papercrane_dispatch`, with `licenseGate: false`. The worker resolves this function through [modalFunctionMap.ts](../../apps/worker/src/providers/modalFunctionMap.ts) and invokes it through the [deployed-function bridge](../../apps/worker/scripts/invoke-deployed-modal.py). The manifest image digest is a placeholder; an immutable deployment digest remains to be recorded.

The dispatch wrapper translates the platform job into FASTA/Protenix inputs, runs inference and returns structure bytes and available confidence metrics. Input/output shape is documented in [schemas/input.json](schemas/input.json) and [schemas/output.json](schemas/output.json). Confidence metrics describe computational predictions; binding requires experimental measurement.

## Retained legacy HTTPS adapter

[adapter.py](adapter.py) contains a separate, optional HTTPS submission/poll/download implementation. It requires a separately supplied compatible service, an HTTPS transport configuration, `AF3_API_ENDPOINT` (or a configured endpoint), and `AF3_API_TOKEN`. The checked-in manifest uses Modal, so calling this adapter directly with that manifest rejects the transport mismatch.

Historical strings in that adapter mention Isomorphic Labs. A working endpoint, access agreement and applicable license would need separate confirmation. The configured Modal path uses its own deployment settings.

## Source and checks

The wrapper credits `biomodals/modal_protenix.py` in its source. Protenix's original research/software authors and terms remain with [its upstream project](https://github.com/bytedance/Protenix); the catalog records Apache-2.0 for Protenix. See the [platform citation inventory](../../THIRD_PARTY/CITATIONS.md).

`tests/` includes fixture-based adapter, manifest and cofolding-contract checks. The platform's `pnpm modal:check` checks source/entrypoint resolution without launching inference. `modal run tools/alphafold3/modal_app.py` runs real remote compute and is not a static check.
