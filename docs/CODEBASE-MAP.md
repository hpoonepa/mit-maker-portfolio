# Code map

The repository keeps the full available implementation for the three projects. The entry points below are the shortest route through the engineering work. Archived source and experimental branches are labeled separately from the paths used in the demonstrations.

## Start here

| Project | Useful entry points |
| --- | --- |
| MiniBinder | [`source-history/scripts/mosaic_5g51_design.py`](../01-minibinder-design/source-history/scripts/mosaic_5g51_design.py) for the resumable campaign runner; [`src/minibinder/cli.py`](../01-minibinder-design/src/minibinder/cli.py) for packaged commands; [`prince/`](../01-minibinder-design/prince/) for structural/site analysis. |
| Paper Crane | [`packages/trpc/src/routers/jobs.ts`](../03-papercrane-platform/packages/trpc/src/routers/jobs.ts) receives jobs; [`apps/worker/src/jobProcessor.ts`](../03-papercrane-platform/apps/worker/src/jobProcessor.ts) runs and persists them; [`tools/`](../03-papercrane-platform/tools/) contains the scientific-tool integrations. |
| SENBA within Paper Crane | [`dynamics/source-original/senba-sprint/`](../03-papercrane-platform/dynamics/source-original/senba-sprint/) contains retained protocols and evaluation; [`dynamics/studio/`](../03-papercrane-platform/dynamics/studio/) runs the saved comparison viewer. |
| SquashVision | [`src/squashvision/backend/squashvision/`](../02-squash-vision/src/squashvision/backend/squashvision/) contains processing and review APIs; [`web/src/features/analysis/`](../02-squash-vision/src/squashvision/web/src/features/analysis/) contains replay, editing and scoring. |

## Folder guide

| Folder | Contents |
| --- | --- |
| [01-minibinder-design](../01-minibinder-design/) | DWV design campaigns, structural review, scoring and retained assay evidence. |
| [01-minibinder-design/src/minibinder](../01-minibinder-design/src/minibinder/) | Python CLI and consolidated campaign modules. |
| [01-minibinder-design/src/minibinder/design](../01-minibinder-design/src/minibinder/design/) | Candidate generation, campaign settings and configurable design losses. |
| [01-minibinder-design/src/minibinder/score](../01-minibinder-design/src/minibinder/score/) | Independent model scoring and retrospective candidate comparison. |
| [01-minibinder-design/backends](../01-minibinder-design/backends/) | Modal, Nebius, RunPod and Vast launch/checkpoint integrations. |
| [01-minibinder-design/legacy](../01-minibinder-design/legacy/) | Original DWV preparation, prediction and scored-candidate scripts. |
| [01-minibinder-design/source-history](../01-minibinder-design/source-history/) | Preserved original-layout campaign source and learning experiments; not a Git history. |
| [01-minibinder-design/prince/prince-model](../01-minibinder-design/prince/prince-model/) | Structure exposure checks, site ranking, research evaluation and CPU examples. |
| [01-minibinder-design/prince/prince-webapp](../01-minibinder-design/prince/prince-webapp/) | Astro/React interface for PRINCE structural inspection and saved evaluation. |
| [01-minibinder-design/results](../01-minibinder-design/results/) | Original measured and computational records, including the first-batch comparison. |
| [02-squash-vision](../02-squash-vision/) | Tracking, calibration, replay and review of squash match footage. |
| [02-squash-vision/src/squashvision/backend](../02-squash-vision/src/squashvision/backend/) | Python processing/API: model loading, tracking, timestamps, geometry and saved shot reviews. |
| [02-squash-vision/src/squashvision/web](../02-squash-vision/src/squashvision/web/) | React application: court setup, synchronized replay, editable shot markers and explicit scoring. |
| [02-squash-vision/research](../02-squash-vision/research/) | Retained diagnostics and experiment notes; historical results remain labeled. |
| [03-papercrane-platform](../03-papercrane-platform/) | Protein-tool platform; backend integrations, worker orchestration, application and research. |
| [03-papercrane-platform/apps/app](../03-papercrane-platform/apps/app/) | Authenticated Next.js dashboard, job wizard and saved structure/results interface. |
| [03-papercrane-platform/apps/api](../03-papercrane-platform/apps/api/) | Fastify/tRPC API, authentication, authorization, SSE and application endpoints. |
| [03-papercrane-platform/apps/worker](../03-papercrane-platform/apps/worker/) | Queued job execution, tool adapters, progress, persistence, cancellation and recovery. |
| [03-papercrane-platform/apps/web](../03-papercrane-platform/apps/web/) | Public website, catalog and landing source, including separately credited contributed code. |
| [03-papercrane-platform/apps/docs](../03-papercrane-platform/apps/docs/) | Public application/API documentation site. |
| [03-papercrane-platform/packages](../03-papercrane-platform/packages/) | Shared API, database, queue, storage, auth, UI, types, observability and other application packages. |
| [03-papercrane-platform/python](../03-papercrane-platform/python/) | Python SDK and adapter contracts. |
| [03-papercrane-platform/tools](../03-papercrane-platform/tools/) | 52 wrappers around credited scientific tools; schemas, manifests, runners and conformance tests. |
| [03-papercrane-platform/binder-scorer](../03-papercrane-platform/binder-scorer/) | Research code for feature preparation, evaluation, calibration and synthetic software examples. |
| [03-papercrane-platform/benchmark](../03-papercrane-platform/benchmark/) | Benchmark inputs, migration code, schemas and manuscript source. |
| [03-papercrane-platform/deploy](../03-papercrane-platform/deploy/) | Deployment and infrastructure configuration; credentials/state excluded. |
| [03-papercrane-platform/docker](../03-papercrane-platform/docker/) | Development services and CPU/CUDA container definitions. |
| [03-papercrane-platform/dynamics](../03-papercrane-platform/dynamics/) | SENBA release/evaluation and Studio, plus clearly separated later untrained Ember research. |
| [03-papercrane-platform/dynamics/studio](../03-papercrane-platform/dynamics/studio/) | Offline saved-data viewer, optional inference server and coordinate preparation. |
| [03-papercrane-platform/dynamics/source-original/senba-sprint](../03-papercrane-platform/dynamics/source-original/senba-sprint/) | Retained SENBA evaluation toolkit, pinned model source, release receipts and research outputs. |
| [03-papercrane-platform/dynamics/src/ember](../03-papercrane-platform/dynamics/src/ember/) | Implemented pocket-ranking research with no trained release in this snapshot. |
| [03-papercrane-platform/dynamics/source-original/dynamics](../03-papercrane-platform/dynamics/source-original/dynamics/) | Original-layout legacy and Ember research source. |
| [03-papercrane-platform/dynamics/senba-audit](../03-papercrane-platform/dynamics/senba-audit/) | Earlier consolidated evaluation copy; not a separate trained model. |
| [docs](../docs/) | Portfolio-wide build notes, source map, current verification and citations. |
| Submission media | Video, figures and PDFs are provided separately from this source-only archive. |

[FOLDERS.csv](FOLDERS.csv) lists every directory containing files, its count and role. [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json) lists the individual files and hashes. The platform’s [tool credits](../03-papercrane-platform/THIRD_PARTY/CITATIONS.md) name all 52 integrations; the folder name identifies a wrapper, not ownership of the underlying scientific model.

## Running and reviewing

The recorded video demonstrates the current interfaces and saved outputs. Studio also has a small offline viewer; its README gives the command. New GPU jobs need separately installed models, cloud credentials and infrastructure. The project READMEs distinguish local tests and saved demos from fresh model inference.

The research folders include experiments that were not promoted to the demonstrated path. Ember has no trained checkpoint; earlier binder experiments and historical manuscript outputs remain reference material. Read the dated results and current project notes together.
