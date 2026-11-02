# Verification commands

Run from the named project directory with its dependencies installed. During assembly, existing local dependencies were used temporarily; dependency folders are not part of the snapshot.

- SquashVision frontend: `vitest run` — 146 passed; `tsc --noEmit` — passed.
- Papercrane `packages/jobs`: `vitest run tests/retry.test.ts tests/transitions.test.ts tests/serde.test.ts` — 40 passed.
- SquashVision backend: `python -m pytest tests/squashvision/backend -q -p no:cacheprovider` — no completed result; imports stalled and a bounded retry timed out after 90 seconds.
- Python syntax: `ast.parse` on each Python source file, without executing it.

The JavaScript checks used Node 22.22.2 on Apple Silicon. An initial frontend attempt with an Intel Node binary could not load the installed Arm Rollup dependency; rerunning with the matching Node installation succeeded.
