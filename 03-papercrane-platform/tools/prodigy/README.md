# PRODIGY

Contact-based binding-affinity prediction for assembled protein-protein complexes.

- Upstream: <https://github.com/haddocking/prodigy>
- Package: <https://pypi.org/project/prodigy-prot/2.4.0/>
- License: Apache-2.0
- Input: a multichain PDB/mmCIF complex with optional disjoint chain-group selection
- Output: predicted binding free energy, dissociation constant, contact-class counts, non-interacting-surface composition, and the analyzed complex as mmCIF

PRODIGY scores an existing complex pose; it does not dock separate monomers. The integration uses the upstream Python API and remains beta until representative complexes pass a live artifact smoke test.
