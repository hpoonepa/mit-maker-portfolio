# Which model powers this interface?

The local worker uses a four-feature residue scorer: exposure, concavity, hydrophobicity, and connectivity. It scores connected patches from the target structure and runs independent structural checks. The interactive validation page presents the corresponding 110-interface retrospective study.

The companion model repository also contains a later XGBoost patch classifier. It uses 660 features and has separate training data, controls, and homology audits. Its prepared-feature inference command is `prince-rank`; it is not the current `/api/analyze` implementation.

The larger model's approximately 0.44–0.46 top-3 result on homology-clean subsets must not be used to label live workspace predictions as validated at that rate. The runtime residue model's macro AUROC is approximately 0.648, close to exposure alone at 0.645. Structural checks and ranking quality are separate claims.

When describing PRINCE, specify the model, endpoint, test population, and control. A patch that is mostly true epitope does not necessarily cover much of the epitope, and neither outcome establishes minibinder success.
