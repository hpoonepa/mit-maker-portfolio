# Release verification — 15 October 2026

The complete Python suite passed: **896 passed, 1 skipped**. The skip is the
optional-SBOL-dependency absence path, which is inapplicable with SBOL installed.
Two SciPy warnings report the documented normal-approximation fallback for exact
statistical tests containing zeros.

Additional checks:

- Both trained model files match the supplied originals byte-for-byte.
- 64 distributed artifact checksums verify.
- Eight real 1JHL patch-feature rows reproduce original XGBoost scores within 1e-6.
- Stable ties, the Jaccard suppression boundary, feature-order mismatch, PCA mismatch,
  malformed shapes, duplicate residues, and non-finite features are covered.
- Wheel and source distributions were built. The source distribution includes the
  research code and evaluation records. The wheel was installed outside the source tree and used to load both models
  and run the prepared-feature example.
- All research Python files compile. The geometry builder, atom builder, and grouped
  sweep commands expose their help from the reorganized repository.
- The companion app's live integration suite passed two real PDB analyses and the
  independent missing-residue STOP case, as well as API and origin checks.

Checks used Python 3.10.9, XGBoost 2.1.0, NumPy 1.23.5, and the existing scientific
packages on the workstation. SBOL3 was installed into a local virtual environment.
This initial run was not a clean installation of every dependency. Subsequent
Python 3.11 checks run from a fresh installation on iGEM's runner; see the
[GitLab pipelines](https://gitlab.igem.org/2026/software/lambert-ga/prince-model/-/pipelines).

The full training study was not rerun. Feature construction, comparator execution,
and external homology analyses require the large inputs described in the reproduction
guide. The frozen metrics retain their original provenance.

`verification.json` contains the compact receipt. Run `python -m pytest` and
`python scripts/verify_artifacts.py` to repeat the repository checks.
