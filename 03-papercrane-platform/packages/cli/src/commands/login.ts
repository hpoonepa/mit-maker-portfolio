import { Command } from "commander";
import chalk from "chalk";
import prompts from "prompts";
import http from "node:http";
import { URL } from "node:url";
import { loadConfig, saveConfig } from "../lib/config.js";
import { ApiClient } from "../lib/api-client.js";
import { ok, info, warn, rootOpts, printJson } from "../lib/output.js";

export function registerLogin(program: Command): void {
  program
    .command("login")
    .description("authenticate with Paper Crane (API key or OAuth via browser)")
    .option("--api-key <key>", "set API key non-interactively")
    .option("--oauth", "force browser OAuth flow")
    .action(async (opts: { apiKey?: string; oauth?: boolean }, cmd) => {
      const root = rootOpts(cmd);
      const cfg = await loadConfig();
      const apiUrl = root.apiUrl ?? cfg.apiUrl;

      let apiKey = opts.apiKey;
      if (!apiKey && !opts.oauth) {
        const ans = await prompts([
          {
            type: "select",
            name: "method",
            message: "How would you like to log in?",
            choices: [
              { title: "Paste API key", value: "key" },
              { title: "OAuth (open browser)", value: "oauth" },
            ],
            initial: 0,
          },
          {
            type: (prev) => (prev === "key" ? "password" : null),
            name: "key",
            message: "API key",
          },
        ]);
        if (ans.method === "key") apiKey = ans.key as string | undefined;
        else opts.oauth = true;
      }

      if (opts.oauth && !apiKey) {
        apiKey = await runOAuthFlow(apiUrl ?? "https://api.papercrane.bio");
      }

      if (!apiKey) {
        warn("no API key provided — aborting");
        process.exitCode = 1;
        return;
      }

      // Verify and pull profile metadata.
      const client = new ApiClient({ apiKey, apiUrl }, cfg);
      const me = await client.query<{
        email: string;
        org: string;
        tier: string;
      }>("me.profile");
      if (!me.ok) {
        warn(`could not verify API key: ${me.error ?? "unknown error"}`);
      }

      await saveConfig({
        ...cfg,
        apiKey,
        apiUrl,
        email: me.data?.email ?? cfg.email,
        org: me.data?.org ?? cfg.org,
        tier: me.data?.tier ?? cfg.tier,
      });

      if (root.json) {
        printJson({ ok: true, email: me.data?.email, org: me.data?.org });
        return;
      }

      ok("API key saved to ~/.config/papercrane/config.toml (chmod 600)");
      if (me.data?.email)
        info(
          `Logged in as ${chalk.bold(me.data.email)} (Org: ${me.data.org}, Tier: ${me.data.tier})`,
        );
    });

  program
    .command("logout")
    .description("remove stored credentials")
    .action(async () => {
      const cfg = await loadConfig();
      await saveConfig({ ...cfg, apiKey: undefined });
      ok("logged out");
    });
}

/**
 * Minimal OAuth callback listener — opens browser to /cli-auth and waits
 * for the redirect with `?token=…`. Falls back to printing the URL.
 */
async function runOAuthFlow(apiUrl: string): Promise<string | undefined> {
  return await new Promise<string | undefined>((resolve) => {
    const server = http.createServer((req, res) => {
      try {
        const url = new URL(req.url ?? "/", "http://localhost");
        const token = url.searchParams.get("token");
        res.writeHead(200, { "content-type": "text/html" });
        res.end(
          token
            ? "<h2>Paper Crane CLI authenticated. You can close this tab.</h2>"
            : "<h2>Missing token.</h2>",
        );
        server.close();
        resolve(token ?? undefined);
      } catch {
        res.writeHead(400);
        res.end();
        server.close();
        resolve(undefined);
      }
    });
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      const cbUrl = `http://127.0.0.1:${port}/cb`;
      const authUrl = `${apiUrl}/cli-auth?cb=${encodeURIComponent(cbUrl)}`;
      info(`Open this URL in your browser:\n  ${chalk.underline(authUrl)}`);
      // Best-effort browser open without adding the `open` dep.
      tryOpen(authUrl);
    });
    setTimeout(
      () => {
        try {
          server.close();
        } catch {
          /* noop */
        }
        resolve(undefined);
      },
      5 * 60 * 1000,
    );
  });
}

function tryOpen(url: string): void {
  const cmd =
    process.platform === "darwin"
      ? "open"
      : process.platform === "win32"
        ? "start"
        : "xdg-open";
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  import("node:child_process").then(({ spawn }) => {
    try {
      spawn(cmd, [url], { stdio: "ignore", detached: true }).unref();
    } catch {
      /* ignore */
    }
  });
}
