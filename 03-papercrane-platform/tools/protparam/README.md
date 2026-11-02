# ProtParam

Protein-sequence physicochemical analysis through Biopython's `ProteinAnalysis` implementation.

- Upstream: <https://biopython.org/>
- Release: <https://github.com/biopython/biopython/blob/biopython-187/NEWS.rst>
- License: Biopython License Agreement (liberal open-source terms; portions are dual-licensed BSD-3-Clause)
- Input: one protein sequence (`sequence` or the first `sequences` record)
- Output: molecular weight, aromaticity, instability index, isoelectric point, GRAVY, charge, extinction coefficients, and a coordinate-free sequence mmCIF

ProtParam analyzes sequence properties and does not predict a fold. The mmCIF artifact records the real polymer sequence and analysis data without fabricated coordinates. This integration remains beta until the pinned CPU image and artifact path pass a live smoke test.
