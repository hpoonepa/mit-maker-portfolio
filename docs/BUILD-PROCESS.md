# Build process

These are the decisions behind the three projects in my video. Each project README links to its source, setup, and results.

## MiniBinder: a good predicted interface was not enough

For about three months, I learned protein-design tools and optimized predicted binders for DWV's VP3 target. [Our first assay](../01-minibinder-design/results/bli/round1-adaptyv-summary.csv) returned nine negative and six unknown/no-loading results: no confirmed binders among 15 designs.

I revised the workflow to consider target accessibility, the binder's standalone fold, sequence properties, and agreement between structural predictors. The [campaign scripts](../01-minibinder-design/source-history/) preserve those iterations. Resumable runners made it possible to compare designs without restarting every interrupted job. [Pipeline notes](../01-minibinder-design/docs/PIPELINE-NOTES.md) separate the campaign from later analysis, including my [PRINCE binding-site tool](../01-minibinder-design/prince/).

The next order contained 20 designs. One of my seven candidates bound the tested construct, with an apparent affinity of 604 nM; Vedant contributed the other thirteen candidates. Adaptyv performed the assays. The original BLI plots are submitted separately; [assay records](../01-minibinder-design/results/bli/round2-adaptyv-summary.csv) remain included. The result establishes binding, but does not identify which redesign caused the improvement or establish viral neutralization.

## Paper Crane: make separate tools work together

Designing one protein meant moving inputs and results between programs. I co-founded Paper Crane and worked on the platform that connects them. The API accepts jobs, workers execute model adapters, and shared state rules keep the dashboard and saved artifacts consistent. I added handling for retries, cancellation, partial outputs, and recovery when a worker stops.

Read the [job architecture](../03-papercrane-platform/docs/portfolio-architecture.md), [shared job package](../03-papercrane-platform/packages/jobs/), and [worker code](../03-papercrane-platform/apps/worker/). The recorded demo (submitted separately) shows the tool catalog, an input form, and a separately saved result. The registry contains 52 entries with different release states.

Within Paper Crane, I built a dynamics model by adapting MarS-FM, then built [SENBA Studio](../03-papercrane-platform/dynamics/studio/) to inspect model endpoints beside recorded MD. The retained comparison improved endpoint error on 27 of 28 validation proteins. A later evaluation with more samples produced a smaller average gain, making sampling sensitivity part of the result. [The dynamics guide](../03-papercrane-platform/dynamics/) links the training receipts, evaluation code, and offline viewer. The later Ember pocket-ranking implementation is included separately and remains untrained.

## SquashVision: make analysis inspectable during replay

I wanted to understand my positioning after matches. I built video processing, court calibration, tracking integration, and a replay interface around existing vision models. A court boundary can constrain detections without being sufficient to measure distance, so playing-area masking and metric calibration are separate steps.

The Canary Wharf demo (submitted separately) shows saved tracking and reviewed shot annotations beside the rally. Court markers link back to their source frames. Corrections create a new report revision, preserving the previous result. The shot ratings are explicit heuristics; they have not been validated against coaching judgments.

Inspect [report corrections](../02-squash-vision/src/squashvision/backend/squashvision/corrections.py), [job recovery](../02-squash-vision/src/squashvision/backend/squashvision/jobs.py), and the [frontend tests](../02-squash-vision/src/squashvision/web/src/). Earlier synthetic fixtures remain available as development evidence, with their provenance recorded.

[Build notes](BUILD-NOTES.md) · [Collaborators and citations](CITATIONS.md)
