# DISCO

Papercrane adapter for DISCO (DIffusion for Sequence-structure CO-design), pinned to upstream commit `82b594f838eb61dd8c78ae3a403ccb8f00cf7abf`.

- Upstream: <https://github.com/DISCO-design/DISCO>
- License: Apache-2.0
- Input: one protein template/length, optionally conditioned on a ligand, DNA, or RNA
- Output: jointly generated protein sequence and mmCIF structure

Papercrane's sequence form supplies the protein length. By default the adapter masks every protein residue (`preserveSequence=false`) so DISCO actually co-designs the sequence and structure. Set `preserveSequence=true` through the API to keep supplied amino acids and only fill explicit `-` positions.

CCD codes and uploaded SDF ligands are supported. Conditional ligand/DNA/RNA jobs automatically default to upstream's recommended `experiment=diverse`, `effort=max`; explicit tool parameters override that choice. DISCO does **not** support protein-target binder design or motif scaffolding, so this adapter does not advertise either capability.

The tool remains beta until its large checkpoint, high-memory fallback attention path, and real R2 upload are smoke-tested on an H100.

Run the remote smoke test with `modal run tools/disco/modal_app.py`.
