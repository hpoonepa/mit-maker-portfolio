# Release verification — 15 October 2026

- `npm ci` completed from the lockfile.
- `npm run check`: 17 source files checked, zero errors, warnings, or hints.
- Production build: seven pages, including the custom 404.
- Link check: 162 internal page and asset references resolved.
- Live HTTP integration: six routes, ten downloads, health and model metadata,
  real 1UBQ analysis, the 6F5J C405/C408 STOP case, invalid input rejection,
  and browser-origin enforcement all passed.

The build emits Vite's size advisory for the lazily loaded Three.js scene.
These initial checks used Node 26.0.0 on this workstation. Subsequent Node 22
checks run on iGEM's runner; see the [GitLab pipelines](https://gitlab.igem.org/2026/software/lambert-ga/prince-webapp/-/pipelines).
CI retains the compiled site and evaluation assets in a compressed archive.
The historical recording remains in the source repository; the deployment guide
explains how to restore it when using the build artifact.

The fresh visual browser check could not complete because the available browser
automation timed out. Fresh screenshots and viewport checks remain pending.
The TypeScript, build, link, and live HTTP checks above did complete.

See `verification.json` for the compact receipt. Run `npm run verify` to repeat
static checks and `npm run integration` with both local services running to
repeat the HTTP checks.
