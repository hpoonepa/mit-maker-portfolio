#!/usr/bin/env node
import { Command } from "commander";
import chalk from "chalk";
import { registerLogin } from "./commands/login.js";
import { registerWhoami } from "./commands/whoami.js";
import { registerProjects } from "./commands/projects.js";
import { registerJobs } from "./commands/jobs.js";
import { registerDesigns } from "./commands/designs.js";

const program = new Command();

program
  .name("papercrane")
  .description(
    chalk.cyan("Paper Crane CLI") +
      " — submit binder design jobs, monitor runs, and manage projects from your terminal.",
  )
  .version("0.1.0")
  .option("--json", "machine-readable JSON output", false)
  .option(
    "--api-url <url>",
    "override API base URL",
    process.env.PAPERCRANE_API_URL ?? "https://api.papercrane.bio",
  );

registerLogin(program);
registerWhoami(program);
registerProjects(program);
registerJobs(program);
registerDesigns(program);

program.showHelpAfterError("(use --help for more info)");

program.parseAsync(process.argv).catch((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err);
  console.error(chalk.red("error: ") + msg);
  process.exit(1);
});
