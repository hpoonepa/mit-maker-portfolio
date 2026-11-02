# Third-party software, models, data, and credits

Paper Crane supplies workflow software and adapters. The scientific methods and model weights below belong to their upstream authors. Paper Crane authorship covers the integration; model authorship remains with the upstream teams. The portfolio MIT license applies only to material its copyright holder can license; it does not replace upstream software, weights, dataset, media, or dependency terms.

The 52 entries below are enumerated from `tools/*/manifest.json`. Versions and license labels are **the checked-in manifest declarations**; applicable terms must be confirmed for each pinned release. Follow the upstream project links for author lists, recommended scientific citations and license texts. Model/runtime pins in each `modal_app.py` and Dockerfile take precedence over a catalog version label. Primary project URLs were checked on 1 November 2026. Historical-version license verification remains incomplete.

| Integration | Upstream project / original maintainers | Manifest version | Recorded license | Local record |
|---|---|---|---|---|
| AlphaFold 3 (Protenix) (`alphafold3`) | [bytedance/Protenix](https://github.com/bytedance/Protenix) | protenix-1.0.4 | Apache-2.0 (Protenix, ByteDance) | [manifest](../tools/alphafold3/manifest.json), [adapter source](../tools/alphafold3/modal_app.py) |
| AntiFold (`antifold`) | [oxpig/AntiFold](https://github.com/oxpig/AntiFold) | 0.3.1 | BSD-3-Clause | [manifest](../tools/antifold/manifest.json), [adapter source](../tools/antifold/modal_app.py) |
| APBS (`apbs`) | [Electrostatics/apbs](https://github.com/Electrostatics/apbs) | 3.4.1 | BSD-3-Clause | [manifest](../tools/apbs/manifest.json), [adapter source](../tools/apbs/modal_app.py) |
| PDBe Arpeggio (`arpeggio`) | [PDBeurope/arpeggio](https://github.com/PDBeurope/arpeggio) | 1.4.4 | GPL-3.0-only | [manifest](../tools/arpeggio/manifest.json), [adapter source](../tools/arpeggio/modal_app.py) |
| AutoDock Vina (`autodock-vina`) | [forlilab/AutoDock-Vina](https://github.com/forlilab/AutoDock-Vina) | 1.2.7 | Apache-2.0 | [manifest](../tools/autodock-vina/manifest.json), [adapter source](../tools/autodock-vina/modal_app.py) |
| BindCraft (`bindcraft`) | [martinpacesa/BindCraft](https://github.com/martinpacesa/BindCraft) | 1.2.0 | MIT | [manifest](../tools/bindcraft/manifest.json), [adapter source](../tools/bindcraft/modal_app.py) |
| Boltz-1 (`boltz1`) | [jwohlwend/boltz](https://github.com/jwohlwend/boltz) | 1.0.0 | MIT | [manifest](../tools/boltz1/manifest.json), [adapter source](../tools/boltz1/modal_app.py) |
| Boltz-2 (`boltz2`) | [jwohlwend/boltz](https://github.com/jwohlwend/boltz) | 2.0.0 | MIT | [manifest](../tools/boltz2/manifest.json), [adapter source](../tools/boltz2/modal_app.py) |
| BoltzGen (`boltzgen`) | [HannesStark/boltzgen](https://github.com/HannesStark/boltzgen) | 0.1.0 | MIT | [manifest](../tools/boltzgen/manifest.json), [adapter source](../tools/boltzgen/modal_app.py) |
| CD-HIT (`cd-hit`) | [weizhongli/cdhit](https://github.com/weizhongli/cdhit) | 4.8.1 | GPL-2.0-only | [manifest](../tools/cd-hit/manifest.json), [adapter source](../tools/cd-hit/modal_app.py) |
| Chai-1 (`chai1`) | [chaidiscovery/chai-lab](https://github.com/chaidiscovery/chai-lab) | 1.0.0 | non-commercial (chaiDiscovery/chai-1 terms) | [manifest](../tools/chai1/manifest.json), [adapter source](../tools/chai1/modal_app.py) |
| Chroma (`chroma`) | [generatebio/chroma](https://github.com/generatebio/chroma) | 1.0.0 | Apache-2.0 | [manifest](../tools/chroma/manifest.json), [adapter source](../tools/chroma/modal_app.py) |
| DIAMOND (`diamond`) | [bbuchfink/diamond](https://github.com/bbuchfink/diamond) | 2.2.4 | GPL-3.0-only | [manifest](../tools/diamond/manifest.json), [adapter source](../tools/diamond/modal_app.py) |
| DISCO (`disco`) | [DISCO-design/DISCO](https://github.com/DISCO-design/DISCO) | 1.0.0 | Apache-2.0 | [manifest](../tools/disco/manifest.json), [adapter source](../tools/disco/modal_app.py) |
| DockQ (`dockq`) | [wallnerlab/DockQ](https://github.com/wallnerlab/DockQ) | 2.1.3 | MIT | [manifest](../tools/dockq/manifest.json), [adapter source](../tools/dockq/modal_app.py) |
| DSSP (`dssp`) | [PDB-REDO/dssp](https://github.com/PDB-REDO/dssp) | 4.6.1 | BSD-2-Clause | [manifest](../tools/dssp/manifest.json), [adapter source](../tools/dssp/modal_app.py) |
| ESM-2 (`esm2`) | [facebookresearch/esm](https://github.com/facebookresearch/esm) | 650M-UR50D | MIT | [manifest](../tools/esm2/manifest.json), [adapter source](../tools/esm2/modal_app.py) |
| ESM-C 300M (`esmc`) | [evolutionaryscale/esm](https://github.com/evolutionaryscale/esm) | 300M-2024-12 | MIT; weights: Cambrian-Open | [manifest](../tools/esmc/manifest.json), [adapter source](../tools/esmc/modal_app.py) |
| ESMFold (`esmfold`) | [facebookresearch/esm](https://github.com/facebookresearch/esm) | 1.0 | MIT | [manifest](../tools/esmfold/manifest.json), [adapter source](../tools/esmfold/modal_app.py) |
| ESM-IF1 (`esmif1`) | [facebookresearch/esm](https://github.com/facebookresearch/esm) | 2.0.0 | MIT | [manifest](../tools/esmif1/manifest.json), [adapter source](../tools/esmif1/modal_app.py) |
| EvoEF2 (`evoef2`) | [tommyhuangthu/EvoEF2](https://github.com/tommyhuangthu/EvoEF2) | 2026.6.22 | MIT | [manifest](../tools/evoef2/manifest.json), [adapter source](../tools/evoef2/modal_app.py) |
| Foldseek (`foldseek`) | [steineggerlab/foldseek](https://github.com/steineggerlab/foldseek) | 10.941cd33 | GPL-3.0 | [manifest](../tools/foldseek/manifest.json), [adapter source](../tools/foldseek/modal_app.py) |
| fpocket (`fpocket`) | [Discngine/fpocket](https://github.com/Discngine/fpocket) | 4.2.3 | MIT | [manifest](../tools/fpocket/manifest.json), [adapter source](../tools/fpocket/modal_app.py) |
| FreeSASA (`freesasa`) | [mittinatten/freesasa](https://github.com/mittinatten/freesasa) | 2.2.1 | MIT | [manifest](../tools/freesasa/manifest.json), [adapter source](../tools/freesasa/modal_app.py) |
| Germinal (`germinal`) | [SantiagoMille/germinal](https://github.com/SantiagoMille/germinal) | 1.0.0 | Apache-2.0 | [manifest](../tools/germinal/manifest.json), [adapter source](../tools/germinal/modal_app.py) |
| HH-suite (`hhsuite`) | [soedinglab/hh-suite](https://github.com/soedinglab/hh-suite) | 3.3.0 | GPL-3.0-only | [manifest](../tools/hhsuite/manifest.json), [adapter source](../tools/hhsuite/modal_app.py) |
| HMMER phmmer (`hmmer`) | [EddyRivasLab/hmmer](https://github.com/EddyRivasLab/hmmer) | 3.4 | BSD-3-Clause | [manifest](../tools/hmmer/manifest.json), [adapter source](../tools/hmmer/modal_app.py) |
| ImmuneBuilder (`immunebuilder`) | [oxpig/ImmuneBuilder](https://github.com/oxpig/ImmuneBuilder) | 1.2 | BSD-3-Clause | [manifest](../tools/immunebuilder/manifest.json), [adapter source](../tools/immunebuilder/modal_app.py) |
| LigandMPNN (`ligandmpnn`) | [dauparas/LigandMPNN](https://github.com/dauparas/LigandMPNN) | 1.0.0 | MIT | [manifest](../tools/ligandmpnn/manifest.json), [adapter source](../tools/ligandmpnn/modal_app.py) |
| MAFFT (`mafft`) | [mafft.cbrc.jp/alignment/software](https://mafft.cbrc.jp/alignment/software/) | 7.526 | BSD-3-Clause | [manifest](../tools/mafft/manifest.json), [adapter source](../tools/mafft/modal_app.py) |
| MDAnalysis (`mdanalysis`) | [MDAnalysis/mdanalysis](https://github.com/MDAnalysis/mdanalysis) | 2.10.0 | LGPL-3.0-or-later | [manifest](../tools/mdanalysis/manifest.json), [adapter source](../tools/mdanalysis/modal_app.py) |
| MMseqs2 (`mmseqs2`) | [soedinglab/MMseqs2](https://github.com/soedinglab/MMseqs2) | 18-8cc5c | MIT | [manifest](../tools/mmseqs2/manifest.json), [adapter source](../tools/mmseqs2/modal_app.py) |
| OmegaFold (`omegafold`) | [HeliXonProtein/OmegaFold](https://github.com/HeliXonProtein/OmegaFold) | 313c873 | Apache-2.0 | [manifest](../tools/omegafold/manifest.json), [adapter source](../tools/omegafold/modal_app.py) |
| OpenMM Relax (`openmm-relax`) | [openmm/openmm](https://github.com/openmm/openmm) | 8.5.2 | MIT/LGPL | [manifest](../tools/openmm-relax/manifest.json), [adapter source](../tools/openmm-relax/modal_app.py) |
| P2Rank (`p2rank`) | [rdk/p2rank](https://github.com/rdk/p2rank) | 2.5.1 | MIT | [manifest](../tools/p2rank/manifest.json), [adapter source](../tools/p2rank/modal_app.py) |
| Parasail (`parasail`) | [jeffdaily/parasail-python](https://github.com/jeffdaily/parasail-python) | 1.3.4 | BSD-3-Clause | [manifest](../tools/parasail/manifest.json), [adapter source](../tools/parasail/modal_app.py) |
| pdb-tools (`pdb-tools`) | [haddocking/pdb-tools](https://github.com/haddocking/pdb-tools) | 2.7.0 | Apache-2.0 | [manifest](../tools/pdb-tools/manifest.json), [adapter source](../tools/pdb-tools/modal_app.py) |
| PDB2PQR (`pdb2pqr`) | [Electrostatics/pdb2pqr](https://github.com/Electrostatics/pdb2pqr) | 3.7.1 | BSD-3-Clause | [manifest](../tools/pdb2pqr/manifest.json), [adapter source](../tools/pdb2pqr/modal_app.py) |
| PDBFixer (`pdbfixer`) | [openmm/pdbfixer](https://github.com/openmm/pdbfixer) | 1.12 | MIT | [manifest](../tools/pdbfixer/manifest.json), [adapter source](../tools/pdbfixer/modal_app.py) |
| PLIP (`plip`) | [pharmai/plip](https://github.com/pharmai/plip) | 3.0.0 | GPL-2.0-only | [manifest](../tools/plip/manifest.json), [adapter source](../tools/plip/modal_app.py) |
| PRODIGY (`prodigy`) | [haddocking/prodigy](https://github.com/haddocking/prodigy) | 2.4.0 | Apache-2.0 | [manifest](../tools/prodigy/manifest.json), [adapter source](../tools/prodigy/modal_app.py) |
| ProDy (`prody`) | [prody/ProDy](https://github.com/prody/ProDy) | 2.6.1 | MIT | [manifest](../tools/prody/manifest.json), [adapter source](../tools/prody/modal_app.py) |
| PROPKA (`propka`) | [jensengroup/propka](https://github.com/jensengroup/propka) | 3.5.1 | LGPL-2.1-only | [manifest](../tools/propka/manifest.json), [adapter source](../tools/propka/modal_app.py) |
| ProteinMPNN (`proteinmpnn`) | [dauparas/ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | 1.0.1 | MIT | [manifest](../tools/proteinmpnn/manifest.json), [adapter source](../tools/proteinmpnn/modal_app.py) |
| ProtParam (`protparam`) | [biopython.org](https://biopython.org/) | 1.87 | Biopython License Agreement | [manifest](../tools/protparam/manifest.json), [adapter source](../tools/protparam/modal_app.py) |
| RoseTTAFold3 (`rf3`) | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) | 0.1.9 | BSD-3-Clause | [manifest](../tools/rf3/manifest.json), [adapter source](../tools/rf3/modal_app.py) |
| RFdiffusion3 (`rfd3`) | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) | 0.1.9 | BSD-3-Clause | [manifest](../tools/rfd3/manifest.json), [adapter source](../tools/rfd3/modal_app.py) |
| RFdiffusion (`rfdiffusion`) | [RosettaCommons/RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) | 1.1.0 | BSD-3-Clause | [manifest](../tools/rfdiffusion/manifest.json), [adapter source](../tools/rfdiffusion/modal_app.py) |
| RFdiffusion All-Atom (`rfdiffusionaa`) | [baker-laboratory/rf_diffusion_all_atom](https://github.com/baker-laboratory/rf_diffusion_all_atom) | 1.0.0 | BSD-3-Clause | [manifest](../tools/rfdiffusionaa/manifest.json), [adapter source](../tools/rfdiffusionaa/modal_app.py) |
| smina (`smina`) | [mwojcikowski/smina](https://github.com/mwojcikowski/smina) | 2019.10.15 | GPL-2.0-only | [manifest](../tools/smina/manifest.json), [adapter source](../tools/smina/modal_app.py) |
| SolubleMPNN (`solublempnn`) | [dauparas/ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | 1.0.1 | MIT | [manifest](../tools/solublempnn/manifest.json), [adapter source](../tools/solublempnn/modal_app.py) |
| ThermoMPNN (`thermompnn`) | [Kuhlman-Lab/ThermoMPNN](https://github.com/Kuhlman-Lab/ThermoMPNN) | 2026.08.10 | MIT | [manifest](../tools/thermompnn/manifest.json), [adapter source](../tools/thermompnn/modal_app.py) |

## Integration-specific corrections and qualifications

- **AlphaFold3 catalog identifier:** [ByteDance Protenix](https://github.com/bytedance/Protenix) supplies the active model. The Modal image installs `protenix==1.0.4` and defaults to `protenix_mini_default_v0.5.0`. The optional `adapter.py` HTTPS implementation requires a separately supplied service and is not the manifest-selected path. The corrected [adapter guide](../tools/alphafold3/README.md) distinguishes both; no official hosted Isomorphic endpoint availability is claimed.
- **Chai-1:** the retained Dockerfile pins `chai_lab==0.5.1`; its [versioned license](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/LICENSE) and [README](https://raw.githubusercontent.com/chaidiscovery/chai-lab/v0.5.1/README.md) identify Apache-2.0 for code and weights. The active Modal image pins `0.6.1`, with [its own Apache license](https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/LICENSE). The noncommercial text in the table records the unchanged legacy manifest label, not the upstream grant. [Policy notes](../tools/chai1/LICENSE-GATE.md) distinguish the retained acknowledgement guard from actual upstream licensing. Recommended research citation: Chai Discovery, *Chai-1: Decoding the molecular interactions of life* (2024), [DOI](https://doi.org/10.1101/2024.10.10.615955).
- **BoltzGen:** the Modal image uses [HannesStark/boltzgen](https://github.com/HannesStark/boltzgen); the older Dockerfile/README names `jwohlwend/boltzgen`. Preserve this distinction when rebuilding.
- **ESM-C:** the manifest records separate Cambrian-Open weights terms for the 2024-12 300M checkpoint. The former EvolutionaryScale repository now redirects to Biohub. The older checkpoint requires its version-specific terms.
- **Germinal:** the manifest notes IgLM and PyRosetta dependency restrictions. Its source still contains an unbuilt placeholder and it is catalog-only in platform readiness configuration.
- **BindCraft and Germinal dependencies:** [ColabDesign](https://github.com/sokrypton/ColabDesign) and [PyRosetta](https://www.pyrosetta.org/) retain their own authorship and applicable terms. Other explicitly imported supporting projects include [OpenFold](https://github.com/aqlaboratory/openfold), [ANARCI](https://github.com/oxpig/ANARCI), [Meeko](https://github.com/forlilab/Meeko), [PDBFixer](https://github.com/openmm/pdbfixer), and [Neurosnap](https://github.com/NeurosnapInc/neurosnap).
- **Selected metric publications:** Foldseek upstream requests [van Kempen et al. (2023)](https://doi.org/10.1038/s41587-023-01773-0); DockQ upstream requests [Mirabello and Wallner (2024)](https://doi.org/10.1093/bioinformatics/btae586). Other method-specific recommended publications are maintained in the linked upstream repositories; no missing author lists or DOIs have been invented here.

## Landing page and visualization credit

The landing application was vendored from [vkalipat/papercrane-website](https://github.com/vkalipat/papercrane-website) at `ca760d7a8fa82044bb1f4cac3549dc9b7b46a455`, recorded in [UPSTREAM.md](../apps/web/landing/UPSTREAM.md). It includes explicitly credited ports from [georgiee/origami](https://github.com/georgiee/origami), with earlier Origami Editor 3D ancestry. [LANDING-ANCESTRY.md](LANDING-ANCESTRY.md) identifies the known contributors, revision evidence and exact bundled MIT/GPL notices. The combined licensing terms require review, and the original contributors retain their credits. The 3D library and structure viewer are [Three.js](https://github.com/mrdoob/three.js) and [Mol*](https://github.com/molstar/molstar).

## Research data and supporting resources

The separate `binder-scorer` work contains original evaluation/contract code and imported scientific data. [Data-source inventory](../binder-scorer/docs/research/2026-06-23-data-source-inventory.md), [combined dataset notes](../binder-scorer/docs/research/2026-06-25-combined-dataset-counts.md), and [target mapping](../binder-scorer/docs/research/2026-06-26-target-fasta-mapping.md) are the local source records. The [file-level dataset provenance map](DATA-PROVENANCE.md) identifies every bundled raw/processed file, its source or generating script, and unresolved terms. Files under `data/raw` and `data/processed` are not covered by the portfolio MIT license merely because they are included. Historical “commercial-OK” planning labels require confirmation against the source terms. `examples/evidence-audit.demo.json`, `examples/evidence-benchmark.demo.json`, and `artifacts/evidence-atlas-v1` contain synthetic demonstration data.

Structure/sequence lookups in the adapters use [RCSB PDB](https://www.rcsb.org/) and the scorer literature retrieval uses [PubMed](https://pubmed.ncbi.nlm.nih.gov/) and [Open Targets](https://platform.opentargets.org/). Cite a structure or dataset by its own accession and source when reporting results. The [benchmark citation record](../benchmark/CITATION.cff) concerns the platform benchmark and does not replace model or dataset citations.

## Platform dependencies

The following list is generated from every checked-in `package.json`, including the vendored landing application. It credits direct external packages, records declared versions, and links their primary package-registry records (with repository/license metadata). Internal `@papercrane/*` workspace packages are excluded. Exact resolved transitive versions remain recorded in `pnpm-lock.yaml` and the landing `package-lock.json`; those lockfiles and package license notices must be retained.

| Direct package | Declared versions | Used by |
|---|---|---|
| [@aws-sdk/client-s3](https://www.npmjs.com/package/@aws-sdk/client-s3) | 3.637.0 | `packages/storage/package.json` |
| [@aws-sdk/s3-request-presigner](https://www.npmjs.com/package/@aws-sdk/s3-request-presigner) | 3.637.0 | `packages/storage/package.json` |
| [@fastify/cors](https://www.npmjs.com/package/@fastify/cors) | 9.0.1 | `apps/api/package.json` |
| [@fastify/rate-limit](https://www.npmjs.com/package/@fastify/rate-limit) | 9.1.0 | `apps/api/package.json` |
| [@fastify/sensible](https://www.npmjs.com/package/@fastify/sensible) | 5.6.0 | `apps/api/package.json` |
| [@mdx-js/loader](https://www.npmjs.com/package/@mdx-js/loader) | ^3.1.0 | `apps/docs/package.json` |
| [@mdx-js/react](https://www.npmjs.com/package/@mdx-js/react) | ^3.1.0 | `apps/docs/package.json` |
| [@next/mdx](https://www.npmjs.com/package/@next/mdx) | ^16.2.4 | `apps/docs/package.json` |
| [@playwright/test](https://www.npmjs.com/package/@playwright/test) | 1.48.2 | `apps/app/package.json` |
| [@prisma/client](https://www.npmjs.com/package/@prisma/client) | 5.18.0 | `packages/db/package.json` |
| [@react-email/components](https://www.npmjs.com/package/@react-email/components) | 0.0.25 | `packages/email/package.json` |
| [@react-email/render](https://www.npmjs.com/package/@react-email/render) | 1.0.1 | `packages/email/package.json` |
| [@sentry/node](https://www.npmjs.com/package/@sentry/node) | 8.26.0 | `apps/api/package.json`, `packages/observability/package.json` |
| [@supabase/ssr](https://www.npmjs.com/package/@supabase/ssr) | 0.5.1 | `apps/app/package.json` |
| [@supabase/supabase-js](https://www.npmjs.com/package/@supabase/supabase-js) | 2.45.0 | `apps/app/package.json`, `apps/web/package.json`, `packages/db/package.json` |
| [@tanstack/react-query](https://www.npmjs.com/package/@tanstack/react-query) | 5.51.21 | `apps/app/package.json` |
| [@testing-library/dom](https://www.npmjs.com/package/@testing-library/dom) | 10.4.0 | `apps/app/package.json` |
| [@testing-library/jest-dom](https://www.npmjs.com/package/@testing-library/jest-dom) | ^6.4.0 | `packages/brand/package.json`, `packages/ui/package.json` |
| [@testing-library/react](https://www.npmjs.com/package/@testing-library/react) | 16.0.0, ^16.0.0 | `apps/app/package.json`, `packages/brand/package.json`, `packages/ui/package.json` |
| [@testing-library/user-event](https://www.npmjs.com/package/@testing-library/user-event) | ^14.5.2 | `packages/ui/package.json` |
| [@trpc/client](https://www.npmjs.com/package/@trpc/client) | 11.0.0-rc.477 | `apps/app/package.json` |
| [@trpc/react-query](https://www.npmjs.com/package/@trpc/react-query) | 11.0.0-rc.477 | `apps/app/package.json` |
| [@trpc/server](https://www.npmjs.com/package/@trpc/server) | 11.0.0-rc.477 | `apps/api/package.json`, `packages/trpc/package.json` |
| [@types/mdx](https://www.npmjs.com/package/@types/mdx) | ^2.0.13 | `apps/docs/package.json` |
| [@types/node](https://www.npmjs.com/package/@types/node) | 20.14.0, 22.4.1, ^20.12.12, ^22.10.1 | `apps/api/package.json`, `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `apps/worker/package.json`, `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `package.json`, `packages/auth/package.json`, `packages/billing/package.json`, `packages/cli/package.json`, `packages/db/package.json`, `packages/email/package.json`, `packages/env/package.json`, `packages/jobs/package.json`, `packages/observability/package.json`, `packages/storage/package.json`, `packages/tools-sdk/package.json`, `packages/trpc/package.json`, `packages/types/package.json`, `scripts/benchmark/package.json`, `scripts/papercrane-cli/package.json`, `scripts/smoke/package.json` |
| [@types/pg](https://www.npmjs.com/package/@types/pg) | 8.11.6, ^8.11.10, ^8.11.6 | `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `scripts/benchmark/package.json` |
| [@types/prompts](https://www.npmjs.com/package/@types/prompts) | 2.4.9, ^2.4.9 | `packages/cli/package.json`, `scripts/papercrane-cli/package.json` |
| [@types/react](https://www.npmjs.com/package/@types/react) | 18.3.12, ^18.3.0, ^18.3.12 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/brand/package.json`, `packages/email/package.json`, `packages/ui/package.json` |
| [@types/react-dom](https://www.npmjs.com/package/@types/react-dom) | ^18.3.0, ^18.3.1 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/brand/package.json`, `packages/ui/package.json` |
| [@types/three](https://www.npmjs.com/package/@types/three) | ^0.170.0 | `apps/web/landing/package.json` |
| [@typescript-eslint/eslint-plugin](https://www.npmjs.com/package/@typescript-eslint/eslint-plugin) | ^8.18.0 | `packages/eslint-config/package.json` |
| [@typescript-eslint/parser](https://www.npmjs.com/package/@typescript-eslint/parser) | ^8.18.0 | `packages/eslint-config/package.json` |
| [@vitejs/plugin-react](https://www.npmjs.com/package/@vitejs/plugin-react) | ^4.3.0 | `packages/brand/package.json`, `packages/ui/package.json` |
| [@vitest/ui](https://www.npmjs.com/package/@vitest/ui) | 2.0.5 | `apps/app/package.json`, `packages/ui/package.json` |
| [ajv](https://www.npmjs.com/package/ajv) | ^8.18.0 | `package.json`, `packages/trpc/package.json` |
| [ajv-formats](https://www.npmjs.com/package/ajv-formats) | ^3.0.1 | `package.json`, `packages/trpc/package.json` |
| [argon2](https://www.npmjs.com/package/argon2) | 0.41.1 | `packages/auth/package.json` |
| [astro](https://www.npmjs.com/package/astro) | ^5.0.0 | `apps/web/landing/package.json` |
| [autoprefixer](https://www.npmjs.com/package/autoprefixer) | ^10.4.20 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json` |
| [bezier-easing](https://www.npmjs.com/package/bezier-easing) | ^2.1.0 | `apps/web/landing/package.json` |
| [bullmq](https://www.npmjs.com/package/bullmq) | 5.13.0 | `apps/api/package.json`, `apps/worker/package.json` |
| [chalk](https://www.npmjs.com/package/chalk) | 5.3.0 | `packages/cli/package.json`, `scripts/papercrane-cli/package.json` |
| [cli-table3](https://www.npmjs.com/package/cli-table3) | 0.6.5 | `packages/cli/package.json` |
| [clsx](https://www.npmjs.com/package/clsx) | *, ^2.1.1 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/ui/package.json` |
| [commander](https://www.npmjs.com/package/commander) | 12.1.0, ^12.1.0 | `benchmark/migrate/package.json`, `packages/cli/package.json`, `scripts/papercrane-cli/package.json` |
| [dotenv](https://www.npmjs.com/package/dotenv) | 16.4.5 | `apps/api/package.json`, `apps/worker/package.json` |
| [eslint](https://www.npmjs.com/package/eslint) | ^9.0.0, ^9.16.0 | `apps/api/package.json`, `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `apps/worker/package.json`, `packages/email/package.json`, `packages/eslint-config/package.json` |
| [eslint-config-next](https://www.npmjs.com/package/eslint-config-next) | 16.2.4 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json` |
| [eslint-plugin-react](https://www.npmjs.com/package/eslint-plugin-react) | ^7.37.2 | `packages/eslint-config/package.json` |
| [eslint-plugin-react-hooks](https://www.npmjs.com/package/eslint-plugin-react-hooks) | ^5.1.0 | `packages/eslint-config/package.json` |
| [execa](https://www.npmjs.com/package/execa) | 9.3.0 | `scripts/smoke/package.json` |
| [fastify](https://www.npmjs.com/package/fastify) | 4.28.1 | `apps/api/package.json` |
| [fastify-plugin](https://www.npmjs.com/package/fastify-plugin) | 4.5.1 | `apps/api/package.json` |
| [fastify-type-provider-zod](https://www.npmjs.com/package/fastify-type-provider-zod) | 1.2.0 | `apps/api/package.json` |
| [fflate](https://www.npmjs.com/package/fflate) | 0.8.2 | `apps/app/package.json` |
| [glob](https://www.npmjs.com/package/glob) | ^10.4.5 | `scripts/benchmark/package.json` |
| [globals](https://www.npmjs.com/package/globals) | ^15.14.0 | `packages/eslint-config/package.json` |
| [handlebars](https://www.npmjs.com/package/handlebars) | 4.7.8 | `scripts/papercrane-cli/package.json` |
| [html2canvas](https://www.npmjs.com/package/html2canvas) | ^1.4.1 | `apps/app/package.json` |
| [ioredis](https://www.npmjs.com/package/ioredis) | 5.4.1 | `apps/api/package.json`, `apps/worker/package.json` |
| [jose](https://www.npmjs.com/package/jose) | 5.8.0 | `packages/auth/package.json` |
| [jsdom](https://www.npmjs.com/package/jsdom) | 24.1.1, ^25.0.0 | `apps/app/package.json`, `packages/brand/package.json`, `packages/ui/package.json` |
| [lucide-react](https://www.npmjs.com/package/lucide-react) | *, ^0.468.0 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/ui/package.json` |
| [molstar](https://www.npmjs.com/package/molstar) | 4.8.0 | `apps/app/package.json`, `apps/web/package.json` |
| [motion](https://www.npmjs.com/package/motion) | ^11.13.1 | `apps/app/package.json`, `apps/web/package.json` |
| [next](https://www.npmjs.com/package/next) | ^16.2.4 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json` |
| [ora](https://www.npmjs.com/package/ora) | 8.1.1 | `packages/cli/package.json` |
| [pg](https://www.npmjs.com/package/pg) | 8.12.0, ^8.11.5, ^8.13.1 | `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `scripts/benchmark/package.json` |
| [pino](https://www.npmjs.com/package/pino) | 9.3.2 | `packages/observability/package.json` |
| [pino-pretty](https://www.npmjs.com/package/pino-pretty) | 11.2.2 | `packages/observability/package.json` |
| [postcss](https://www.npmjs.com/package/postcss) | ^8.4.49 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json` |
| [prettier](https://www.npmjs.com/package/prettier) | ^3.4.2 | `package.json` |
| [prisma](https://www.npmjs.com/package/prisma) | 5.18.0 | `packages/db/package.json` |
| [prom-client](https://www.npmjs.com/package/prom-client) | 15.1.3 | `packages/observability/package.json` |
| [prompts](https://www.npmjs.com/package/prompts) | 2.4.2 | `packages/cli/package.json`, `scripts/papercrane-cli/package.json` |
| [react](https://www.npmjs.com/package/react) | 18.3.1, ^18.0.0 || ^19.0.0, ^18.3.1 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/brand/package.json`, `packages/email/package.json`, `packages/ui/package.json` |
| [react-dom](https://www.npmjs.com/package/react-dom) | ^18.0.0 || ^19.0.0, ^18.3.1 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/brand/package.json`, `packages/ui/package.json` |
| [rehype-slug](https://www.npmjs.com/package/rehype-slug) | ^6.0.0 | `apps/docs/package.json` |
| [remark-gfm](https://www.npmjs.com/package/remark-gfm) | ^4.0.0 | `apps/docs/package.json` |
| [resend](https://www.npmjs.com/package/resend) | 4.0.1 | `packages/email/package.json` |
| [shaders](https://www.npmjs.com/package/shaders) | ^2.5.110 | `apps/web/landing/package.json` |
| [shiki](https://www.npmjs.com/package/shiki) | ^1.24.4 | `apps/docs/package.json` |
| [smol-toml](https://www.npmjs.com/package/smol-toml) | 1.3.1 | `packages/cli/package.json` |
| [split-type](https://www.npmjs.com/package/split-type) | ^0.3.4 | `apps/web/landing/package.json` |
| [stripe](https://www.npmjs.com/package/stripe) | 16.2.0 | `packages/billing/package.json` |
| [superjson](https://www.npmjs.com/package/superjson) | 2.2.1 | `apps/app/package.json`, `packages/trpc/package.json` |
| [tailwind-merge](https://www.npmjs.com/package/tailwind-merge) | *, ^2.5.0, ^2.5.5 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/ui/package.json` |
| [tailwindcss](https://www.npmjs.com/package/tailwindcss) | ^3.4.15 | `apps/app/package.json`, `apps/docs/package.json`, `apps/web/package.json`, `packages/ui/package.json` |
| [three](https://www.npmjs.com/package/three) | ^0.170.0 | `apps/web/landing/package.json` |
| [trpc-to-openapi](https://www.npmjs.com/package/trpc-to-openapi) | 2.1.0 | `packages/trpc/package.json` |
| [tsx](https://www.npmjs.com/package/tsx) | 4.16.2, 4.19.0, ^4.16.0, ^4.19.0, ^4.19.2 | `apps/api/package.json`, `apps/worker/package.json`, `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `packages/db/package.json`, `scripts/benchmark/package.json`, `scripts/papercrane-cli/package.json`, `scripts/smoke/package.json` |
| [turbo](https://www.npmjs.com/package/turbo) | ^2.3.3 | `package.json` |
| [typescript](https://www.npmjs.com/package/typescript) | 5.5.3, ^5.5.2, ^5.6.0, ^5.7.2 | `apps/api/package.json`, `apps/app/package.json`, `apps/docs/package.json`, `apps/web/landing/package.json`, `apps/web/package.json`, `apps/worker/package.json`, `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `package.json`, `packages/auth/package.json`, `packages/billing/package.json`, `packages/brand/package.json`, `packages/cli/package.json`, `packages/db/package.json`, `packages/email/package.json`, `packages/env/package.json`, `packages/jobs/package.json`, `packages/observability/package.json`, `packages/storage/package.json`, `packages/tools-sdk/package.json`, `packages/trpc/package.json`, `packages/types/package.json`, `packages/ui/package.json`, `scripts/benchmark/package.json`, `scripts/papercrane-cli/package.json`, `scripts/smoke/package.json` |
| [ulid](https://www.npmjs.com/package/ulid) | ^2.3.0 | `scripts/benchmark/package.json` |
| [vega](https://www.npmjs.com/package/vega) | 5.30.0 | `benchmark/preprint/package.json` |
| [vega-lite](https://www.npmjs.com/package/vega-lite) | 5.21.0 | `benchmark/preprint/package.json` |
| [vitest](https://www.npmjs.com/package/vitest) | 1.6.0, 2.0.5, ^1.6.0, ^2.1.8 | `apps/api/package.json`, `apps/app/package.json`, `apps/worker/package.json`, `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `package.json`, `packages/auth/package.json`, `packages/billing/package.json`, `packages/brand/package.json`, `packages/cli/package.json`, `packages/db/package.json`, `packages/email/package.json`, `packages/env/package.json`, `packages/jobs/package.json`, `packages/observability/package.json`, `packages/storage/package.json`, `packages/tools-sdk/package.json`, `packages/trpc/package.json`, `packages/types/package.json`, `packages/ui/package.json`, `scripts/benchmark/package.json`, `scripts/papercrane-cli/package.json`, `scripts/smoke/package.json` |
| [yaml](https://www.npmjs.com/package/yaml) | ^2.4.5 | `scripts/benchmark/package.json` |
| [zod](https://www.npmjs.com/package/zod) | 3.23.8, ^3.23.8 | `apps/api/package.json`, `apps/app/package.json`, `apps/worker/package.json`, `benchmark/migrate/package.json`, `benchmark/preprint/package.json`, `packages/billing/package.json`, `packages/email/package.json`, `packages/env/package.json`, `packages/jobs/package.json`, `packages/tools-sdk/package.json`, `packages/trpc/package.json`, `packages/types/package.json` |

Python direct dependencies are declared in the following source manifests. [PyPI](https://pypi.org/) project metadata and upstream repositories provide their individual notices; uv lockfiles retain exact resolved versions.

| Python manifest | Declared dependency |
|---|---|
| `binder-scorer/pyproject.toml` | [lightgbm>=4.5](https://pypi.org/project/lightgbm/) |
| `binder-scorer/pyproject.toml` | [numpy>=2.0](https://pypi.org/project/numpy/) |
| `binder-scorer/pyproject.toml` | [pytest>=9](https://pypi.org/project/pytest/) |
| `binder-scorer/pyproject.toml` | [scikit-learn>=1.5](https://pypi.org/project/scikit-learn/) |
| `binder-scorer/pyproject.toml` | [scipy>=1.14](https://pypi.org/project/scipy/) |
| `python/papercrane-sdk/pyproject.toml` | [jsonschema>=4.23](https://pypi.org/project/jsonschema/) |
| `python/papercrane-sdk/pyproject.toml` | [pydantic>=2.7](https://pypi.org/project/pydantic/) |
| `python/papercrane-sdk/pyproject.toml` | [pytest-cov>=5.0](https://pypi.org/project/pytest-cov/) |
| `python/papercrane-sdk/pyproject.toml` | [pytest>=8.0](https://pypi.org/project/pytest/) |
| `python/papercrane-sdk/pyproject.toml` | [pyyaml>=6.0](https://pypi.org/project/pyyaml/) |

Infrastructure and services are supplied by [Modal](https://modal.com/docs), [Cloudflare R2](https://developers.cloudflare.com/r2/), [Supabase](https://supabase.com/docs), [PostgreSQL](https://www.postgresql.org/docs/), [Redis](https://redis.io/docs/), [BullMQ](https://docs.bullmq.io/), [Stripe](https://docs.stripe.com/), [Resend](https://resend.com/docs/), [Sentry](https://docs.sentry.io/), [Fly.io](https://fly.io/docs/), and [Vercel](https://vercel.com/docs). These services retain their own terms. The source contains reserved Vast/RunPod configuration fields; they are not implemented worker providers in this snapshot.

This inventory records sources and credits. Run verification is tool-specific; software, weights, data and media retain their respective terms.
