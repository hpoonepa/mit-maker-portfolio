# Snapshot checks

## Source snapshot checks — 1 November 2026

Checks ran on this candidate's source using existing local dependencies. No pretrained model weights were downloaded and no real-footage inference or browser workflow was run.

| Check | Result |
| --- | --- |
| Frontend unit/component suite | **234 passed in 31 files**, Vitest 3.2.7. |
| Full TypeScript check, including tests | Passed (`tsc --noEmit`). |
| Production TypeScript check | Passed (`tsc -p tsconfig.build.json`). |
| Vite production build | Passed, 148 modules; existing bundle-size advisory for the 566.81 kB JavaScript chunk. |
| Python syntax | All **105 files parsed**; no errors. |
| Python semantic comparison | **104 ASTs equal to readable canonical source**; the remaining Python source fallback could not be compared because its canonical file was offloaded. |
| Shell and CommonJS syntax | `bash -n start.sh` and all five CJS syntax checks passed. |
| Canonical source restoration | 201 recorded inserted-purpose comments removed only when the remainder matched the available canonical source byte for byte. |
| Backend pytest suite | **555 distinct tests passed**: 537 in the initial run, then the 18 loopback-dependent tests on a permitted local-server rerun. |

Frontend checks used native Node 22.22.2 and a disposable copy of the existing locked dependency tree. Build output stayed outside the source snapshot. The separate full TypeScript check includes test files; the production configuration excludes them.

The first Python environment stalled while importing its NumPy native extension; that attempt timed out without results. The installed application's Python 3.12.13 runtime loaded the same pinned scientific dependencies successfully. It then ran candidate application code, with pytest/pytest-asyncio supplied from the existing development environment. The full suite produced 537 passes and 18 sandbox loopback-binding errors; rerunning only those 18 tests with local-server permission passed all 18. The combined count is 555 distinct tests, without counting any rerun twice. Data and model-server fixtures were disposable and kept under temporary directories. FastAPI emitted one dependency deprecation warning about Starlette's HTTPX test client.

## Source integrity

[The source receipt](SOURCE-SNAPSHOT.json) records hashes and original paths at portfolio assembly, including the eighteen local experiment helpers and archived technical notes. The [prior 31 October receipt](SOURCE-SNAPSHOT-2026-10-31.json) is retained separately. Two pre-existing TypeScript test repairs remain: eight unsupported `exact` options in two role-query test files were removed while preserving literal accessible names. The fresh full suite covers those tests.

Two canonical files remain iCloud-offloaded: `scripts/verify-stats.cjs` and `tests/squashvision/backend/test_playback_impacts.py`. Their earlier recorded fallback copies are retained; canonical equality is not asserted. Three other formerly offloaded files were now readable and compared. The original working folders were not edited.

The archived development notes contain earlier recorded checks, including model and browser runs. Those reports are historical evidence, not additional fresh passes. None of these checks measures model accuracy, coaching agreement or generalization to another court.
