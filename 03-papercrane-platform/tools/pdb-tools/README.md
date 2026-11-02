# pdb-tools

Dependency-light PDB cleanup, canonical formatting, and validation.

- Upstream: <https://github.com/haddocking/pdb-tools>
- Package: <https://pypi.org/project/pdb-tools/2.7.0/>
- License: Apache-2.0 (the upstream license also preserves notices for bundled formatting code)
- Input: PDB/mmCIF protein structure with optional chain, heteroatom, and hydrogen filters
- Output: cleaned atom/residue/chain counts, validation issue counts, removal counts, and cleaned mmCIF

The integration converts mmCIF inputs to PDB, invokes the official `pdb_*` tools without shell pipelines, validates the result, and converts the real cleaned coordinates back to mmCIF. It remains beta until representative structures pass a live artifact smoke test.
