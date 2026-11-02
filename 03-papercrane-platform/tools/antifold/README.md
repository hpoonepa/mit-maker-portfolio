# AntiFold

Papercrane beta adapter for AntiFold 0.3.1. AntiFold samples antibody or nanobody CDR sequences against a fixed variable-domain backbone, then Papercrane uploads that backbone as mmCIF together with the sampled sequence and native AntiFold scores.

Inputs must use IMGT residue numbering. The adapter accepts paired heavy/light chains, a nanobody chain, and an optional antigen chain. It defaults to redesigning CDR1, CDR2, and CDR3 at temperature 0.2.

AntiFold is BSD-3-Clause and published by Oxford Protein Informatics Group.
