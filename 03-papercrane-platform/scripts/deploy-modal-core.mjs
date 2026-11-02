import { spawnSync } from "node:child_process";

const apps = [
  "tools/rfdiffusion/modal_app.py",
  "tools/proteinmpnn/modal_app.py",
  "tools/boltz2/modal_app.py",
];

for (const app of apps) {
  const args = ["deploy", app];
  if (process.env.MODAL_ENVIRONMENT) {
    args.push("--env", process.env.MODAL_ENVIRONMENT);
  }
  const result = spawnSync("modal", args, { stdio: "inherit" });
  if (result.error) {
    console.error(`Could not start Modal deployment for ${app}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

console.log("Core Modal workflow apps deployed successfully.");
