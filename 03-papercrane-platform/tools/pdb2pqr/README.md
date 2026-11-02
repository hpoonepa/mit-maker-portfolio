# PDB2PQR

Open-source preparation of biomolecular structures for continuum electrostatics, including protonation, hydrogen optimization, and force-field charge/radius assignment.

- Upstream release: <https://github.com/Electrostatics/pdb2pqr/releases/tag/v3.7.1>
- Official CLI documentation: <https://pdb2pqr.readthedocs.io/en/stable/using/index.html>
- Upstream license: <https://github.com/Electrostatics/pdb2pqr/blob/v3.7.1/LICENSE.md>
- License: BSD-3-Clause
- Input: PDB/mmCIF protein structure
- Output: prepared structure as mmCIF plus atom, hydrogen, radius, and net-charge summaries

The adapter pins PDB2PQR 3.7.1 and PROPKA 3.5.1. It runs `pdb2pqr --ff ... --titration-state-method propka --with-ph ...`, requests PDB2PQR's prepared PDB output, and converts that real prepared structure to mmCIF. It remains beta until representative force fields and input formats pass live image and artifact-upload smoke tests.
