# APBS

Open-source Poisson–Boltzmann electrostatics for biomolecular structures.

- Upstream release: <https://github.com/Electrostatics/apbs/releases/tag/v3.4.1>
- Official input documentation: <https://apbs.readthedocs.io/en/latest/using/input/old/>
- Official PQR documentation: <https://apbs.readthedocs.io/en/latest/formats/pqr.html>
- Upstream license: <https://github.com/Electrostatics/apbs/blob/v3.4.1/LICENSE.md>
- License: BSD-3-Clause
- Input: PDB/mmCIF protein structure
- Output: PDB2PQR-prepared structure as mmCIF, electrostatic energy, and OpenDX potential-grid summary

The adapter pins the official APBS 3.4.1 Linux release archive by SHA-256 and composes PDB2PQR 3.7.1 preparation inside its own execution path. It performs one linear or nonlinear Poisson–Boltzmann calculation and summarizes the generated potential grid without uploading the much larger OpenDX file. It remains beta until the release binary, grid sizing, and energy parser pass live smoke tests.
