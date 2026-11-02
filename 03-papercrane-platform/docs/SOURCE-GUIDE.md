# Source map

| Directory | Code to read |
|---|---|
| [apps/app](../apps/app/) | Dashboard, job forms, structure viewer, exports and UI tests |
| [apps/api](../apps/api/) | Fastify server, authentication, REST routes and health checks |
| [apps/worker](../apps/worker/) | Queue processing, Modal dispatch, cancellation and recovery |
| [apps/web](../apps/web/) | Public website and vendored Astro landing source |
| [apps/docs](../apps/docs/) | Tool and API documentation application |
| [packages/trpc](../packages/trpc/) | Typed API routers, validation and organization access |
| [packages/db](../packages/db/) | Prisma schema, migrations, seeds and credential encryption |
| [packages/jobs](../packages/jobs/) | Queue contracts, job events and state transitions |
| [packages](../packages/) | Storage, authentication, UI, billing, email, observability, CLI and shared types |
| [tools](../tools/) | Model manifests, schemas, Modal apps, adapters and fixtures |
| [python](../python/) | Python adapter SDK and contract tests |
| [binder-scorer](../binder-scorer/) | Ranking research, features, evaluation and data contracts |
| [benchmark](../benchmark/) | Targets, data migration and evaluation methodology |
| [scripts](../scripts/) | Setup, scaffolding, smoke checks and deployment scripts |
| [docker](../docker/) and [deploy](../deploy/) | Container images and infrastructure definitions |
| [dynamics](../dynamics/) | Trained SENBA source, Studio, evaluation and unfinished Ember research |

For one job's path through the platform, read the [jobs router](../packages/trpc/src/routers/jobs.ts), [worker processor](../apps/worker/src/jobProcessor.ts), [Modal runner](../apps/worker/src/adapters/_modalRunner.ts), and [deployed-function bridge](../apps/worker/scripts/invoke-deployed-modal.py). The [designs router](../packages/trpc/src/routers/designs.ts) serves saved results.

The [readiness configuration](../packages/trpc/src/config/toolReadiness.ts) separates 12 GA-labelled tools, 39 submission-enabled beta tools and the catalog-only Germinal stub. The [registry](../apps/worker/src/adapters/registry.ts) has all 52 entries. Static registration is separate from a successful live run.

The public landing page retains its [upstream credit](../apps/web/landing/UPSTREAM.md), including origami implementation attribution. The platform wraps existing scientific tools; their licenses and model-access requirements remain with their respective projects.

[Local setup](setup.md) explains services and credentials. [Verification notes](portfolio-architecture.md) record the checks run on this snapshot.
