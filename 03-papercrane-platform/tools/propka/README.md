# PROPKA

Open-source empirical prediction of pKa values for ionizable groups in protein and protein-ligand structures.

- Upstream release: <https://github.com/jensengroup/propka/releases/tag/v3.5.1>
- Official CLI documentation: <https://propka.readthedocs.io/en/stable/command.html>
- Upstream license: <https://github.com/jensengroup/propka/blob/v3.5.1/LICENSE>
- License: LGPL-2.1-only
- Input: PDB/mmCIF protein structure
- Output: analyzed structure as mmCIF plus per-residue pKa metrics and aggregate summaries

The adapter pins PROPKA 3.5.1 and invokes the official `propka3 --pH ...` CLI. Residue predictions from the `SUMMARY OF THIS PREDICTION` section are exposed as numeric `pka_<group>_<chain>_<residue>` metrics. It remains beta until diverse residue numbering and ligand-containing structures pass live smoke tests.
