# smina

Open-source CPU docking and minimization derived from AutoDock Vina with additional scoring functions and direct molecular-format support.

- Official project files: <https://sourceforge.net/projects/smina/files/>
- Official source and CLI reference: <https://sourceforge.net/p/smina/code/ci/master/tree/>
- License texts mirrored upstream: <https://github.com/mwojcikowski/smina>
- Effective binary license: GPL-2.0-only (the source also contains Apache-2.0 AutoDock Vina components)
- Input: receptor structure and required SDF ligand or SMILES
- Output: top docked protein-ligand complex as mmCIF and docking-affinity summary

smina can automatically define the search box around an uploaded SDF whose coordinates are already in the receptor frame. SMILES-generated conformers have arbitrary coordinates and therefore require explicit `boxCenter` and `boxSize` parameters.

smina does not publish semantic releases. This adapter therefore pins the current official `smina.static` distribution dated 2019-10-15 by its SHA-256 digest, `ffe5e1e78c947f76b0df8805e2c54383d0bbaf2e827a633b643a708cf682a958`, rather than assigning a fictional upstream version. It remains beta until Linux binary compatibility, docking, and SDF pose export pass live smoke tests.
