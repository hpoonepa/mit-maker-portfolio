# Run SquashVision locally

Run these commands from `02-squash-vision`. Install Python 3.12+, uv and native
Node 22.12+ first. The backend supplies its FFmpeg dependency and downloads
approved third-party model weights on request. Those weights retain their own
licenses. The pose loader supports Apple Silicon or compatible Linux hardware
and rejects Intel macOS.

```sh
uv sync --project src/squashvision/backend --group dev
npm ci --prefix src/squashvision/web
./start.sh --data-dir ./local-data
```

Open `http://127.0.0.1:8950` after the launcher reports readiness. Stop with
Ctrl+C. Import your footage, check model readiness, draw the playing area and
start tracking. Optional court calibration enables metric estimates where the
visible geometry supports them. A new library starts empty; the recorded demo's
private library and imported video are not bundled.

`start.sh` builds the web app and starts the API and worker. It uses the backend
environment created by `uv sync`; `SQUASHVISION_PYTHON` and `SQUASHVISION_NODE`
can select other installed runtimes. Additional arguments go to the launcher,
including `--api-port` and `--data-dir`.

```sh
uv run --project src/squashvision/backend pytest tests/squashvision/backend
npm test --prefix src/squashvision/web -- --run
npm run typecheck --prefix src/squashvision/web
npm run build --prefix src/squashvision/web
```

The production build excludes test files. The separate `typecheck` command
includes them. Browser tests require a running local app and an installed
Playwright browser:

```sh
SQUASHVISION_E2E_BASE_URL=http://127.0.0.1:8950 npm run e2e --prefix src/squashvision/web
```

The scripts under `research/helpers` preserve local diagnostic work and require
their original data paths and saved match IDs. They are separate from normal
application startup.
