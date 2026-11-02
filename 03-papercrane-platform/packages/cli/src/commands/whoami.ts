import { Command } from "commander";
import chalk from "chalk";
import { ApiClient } from "../lib/api-client.js";
import { loadConfig } from "../lib/config.js";
import { fail, printJson, rootOpts } from "../lib/output.js";

export function registerWhoami(program: Command): void {
  program
    .command("whoami")
    .description("show the currently authenticated user, org, and tier")
    .action(async (_opts, cmd) => {
      const root = rootOpts(cmd);
      const cfg = await loadConfig();
      const client = new ApiClient({ apiUrl: root.apiUrl }, cfg);

      if (!client.hasAuth()) {
        if (root.json) {
          printJson({ ok: false, error: "not logged in" });
          process.exitCode = 1;
          return;
        }
        fail("not logged in — run `papercrane login`");
      }

      const res = await client.query<{
        email: string;
        org: string;
        tier: string;
      }>("me.profile");

      // Fall back to cached values if the API is unreachable (e.g. dev mode).
      const email = res.data?.email ?? cfg.email ?? "unknown";
      const org = res.data?.org ?? cfg.org ?? "unknown";
      const tier = res.data?.tier ?? cfg.tier ?? "unknown";

      if (root.json) {
        printJson({ email, org, tier, online: res.ok });
        return;
      }

      process.stdout.write(
        `Logged in as ${chalk.bold.cyan(email)} (Org: ${chalk.bold(org)}, Tier: ${chalk.green(tier)})\n`,
      );
      if (!res.ok) {
        process.stderr.write(
          chalk.yellow("(showing cached profile — API unreachable)\n"),
        );
      }
    });
}
