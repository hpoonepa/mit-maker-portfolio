#!/usr/bin/env node
// Friendly nudge after `npm i -g @papercrane/cli` — non-fatal, never blocks install.
try {
  if (process.env.PAPERCRANE_CLI_QUIET === "1") process.exit(0);
  const msg = [
    "",
    "  [36mPaper Crane CLI installed.[0m",
    "  Run: [1mpapercrane login[0m to authenticate.",
    "  Docs: https://papercrane.bio/docs/cli",
    "",
  ].join("\n");
  process.stdout.write(msg);
} catch {
  /* ignore */
}
