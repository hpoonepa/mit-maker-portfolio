# Code map

The complete application is under `src/squashvision`; the portfolio adds demonstrations, citations and source receipts around it.

| Path | Role |
| --- | --- |
| `start.sh`, `src/squashvision/launcher.py` | Build the web interface, start the local API/worker and manage the selected data directory. |
| `src/squashvision/backend/squashvision/app.py`, `routes/` | FastAPI application and endpoints for imports, jobs, calibration, review, corrections, model readiness and exports. |
| `backend/squashvision/media.py`, `model_assets.py`, `storage.py` | Frame/time handling, verified external model assets and local storage. Paths in this and following backend rows are relative to `src/squashvision/`. |
| `backend/squashvision/pipeline.py`, `jobs.py`, `worker.py` | Durable processing stages, scheduling and cancellation/recovery. |
| `backend/squashvision/vision/` | Player identity/pose integration, adapted TrackNetV3 ball inference, contacts, rallies and shot estimates. |
| `backend/squashvision/calibration.py`, `player_roi` routes | Court-coordinate mapping and a separate image-space playing-area constraint. |
| `backend/squashvision/shot_review.py`, `corrections.py`, `analytics.py`, `tracking_stats.py`, `playback_impacts.py` | Editable evidence, report revisions, retained-interval measurements and replay events. |
| `backend/migrations/` | Fifteen schema migrations and Alembic environment. |
| `web/src/features/` | Match library/upload, setup, processing, replay/analysis, review queue and reports. |
| `web/src/api/`, `web/src/styles/` | API contracts/decoders and interface styles. |
| `tests/squashvision/backend/`, `web/src/**/*.test.*`, `web/e2e/` | Backend, frontend and browser tests. |
| `scripts/` | Fixture generation, API synchronization, calibration and local verification helpers. |
| `research/helpers/`, `research/local-notes/` | Eighteen preserved local experiments and four archived run notes; the helpers expect original data paths and saved IDs. |
| `assets/`, `tests/squashvision/fixtures/` | Portfolio media and documented test inputs. |

## Development notes

The [original technical README](WORKING_SOURCE_README.md) and working notes are retained for context. Their saved-run statistics and historical checks describe those runs, rather than fresh validation of this snapshot:

- [Demo walkthrough](demo-walkthrough.md) and [personal demo](personal-demo.md)
- [Ball tracking check](ball-tracking-check.md) and [ball contrast](ball-contrast.md)
- [Identity audit](identity-audit.md), [calibration confidence](calibration-confidence.md) and [tracking statistics](tracking-stats.md)
- [Design notes](design-notes.md) and [match console design](match-console-design.md)

[Setup](SETUP.md) describes normal startup; [verification](VERIFICATION.md) separates new checks from earlier evidence. Runtime databases, uploaded recordings, downloaded checkpoints, dependency folders and temporary browser state are excluded. The recorded file-level history is in [source history](SOURCE_HISTORY.md), not inferred from file modification dates.
