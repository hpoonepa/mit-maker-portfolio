# Paper Crane dynamics

Submission figures are provided separately; this source-only archive retains the viewer, evaluation code and result records.

I built SENBA to study protein conformation changes, then built Studio to inspect its predictions beside recorded molecular dynamics. SENBA adapts the MarS-FM model to mdCATH transitions at 450 K with targets 50 saved frames after the input. The released checkpoint retains 7.35% of a ten-epoch fine-tuning update through weight interpolation with the source model.

[Open Studio locally](studio/README.md). Its saved viewer includes four real transitions from the 52-residue 1rquA01 domain, sixteen endpoint samples per model, and 51 recorded MD frames per transition. It runs offline with Python's standard library and bundled Three.js. The Senba, Source model, MD endpoint and MD movie tabs share the same input. A model morph interpolates between displayed coordinates; recorded MD playback uses chronological simulation frames. Display speed does not represent physical time.

The released validation receipt reports lower ensemble-mean endpoint error on 27 of 28 proteins, with a mean gain of 0.03259 angstrom over source MarS-FM. These proteins were used for validation and selection. The comparison does not establish independent test performance or improved physical dynamics.

I subsequently implemented an evaluation on eight reused validation proteins. At sixteen draws per model, the endpoint gain was 0.01383 angstrom, smaller than the four-draw estimate. [Results and limitations](source-original/senba-sprint/RESULTS_SUMMARY.md) explain the sampling sensitivity. [Full source, tests, protocols and receipts](source-original/senba-sprint/) include the upstream model implementation. Original adaptation scripts and exact adaptation CSVs are unavailable; the released training receipts remain included. Model weights and bulk trajectories are external.

Ember is the later pocket-ranking work in [src/ember](src/ember/) and [its original layout](source-original/dynamics/ember/). Its model, training and inference code is implemented, with local contract checks. It has no trained checkpoint or measured predictive performance. [The work log](source-original/dynamics/ember/WORK_LOG.md) records that boundary.

Credits: MarS-FM source and model, Valence Labs, MIT license; mdCATH simulation data, CC BY 4.0. Studio retains the Three.js MIT license.

[Build notes](docs/BUILD-NOTES.md) · [Sources, papers and licenses](CITATIONS.md)
