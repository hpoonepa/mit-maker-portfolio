# Germinal

Germinal is catalogued for epitope-targeted antibody and nanobody design. Its
upstream code is Apache-2.0, but IgLM and PyRosetta dependencies add
non-commercial restrictions, so Papercrane treats it as a frontier tool.

This adapter is **not runnable yet**. The Modal image still contains a zeroed
upstream commit placeholder and has not completed a production image build.
The catalog exposes that state explicitly and `jobs.submit` rejects it before
reserving compute.

Input and output contracts live in `schemas/input.json` and
`schemas/output.json`.
