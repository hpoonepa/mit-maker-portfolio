# ESM-C 300M

Papercrane's ESM-C adapter scores or embeds amino-acid sequences with the
open-weight 300M model. It accepts sequence input through the job wizard and
emits one NDJSON seed event per requested run.

- Modal app: `papercrane-esmc`
- Entrypoint: `papercrane_dispatch`
- Default mode: `score` with mean pooling
- Release state: runnable beta; live production verification is still limited

Input and output contracts live in `schemas/input.json` and
`schemas/output.json`.
