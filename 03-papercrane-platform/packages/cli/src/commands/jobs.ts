import { Command } from "commander";
import ora from "ora";
import chalk from "chalk";
import { ApiClient, requireAuth } from "../lib/api-client.js";
import { fail, ok, printJson, printTable, rootOpts } from "../lib/output.js";
import { resolveProjectId } from "./projects.js";

interface Job {
  id: string;
  toolId: string;
  status:
    | "queued"
    | "preparing"
    | "running"
    | "partial"
    | "succeeded"
    | "failed"
    | "cancelling"
    | "cancelled"
    | "purged";
  numDesigns: number;
  completedDesigns: number;
  submittedAt: string;
  startedAt?: string;
  finishedAt?: string;
  errorMessage?: string;
}

export interface JobLog {
  id: string;
  level: "info" | "warn" | "error";
  event: string;
  message: string;
  metadata: Record<string, unknown> | null;
  createdAt: string;
}

const STATUS_COLOR: Record<Job["status"], (s: string) => string> = {
  queued: chalk.gray,
  preparing: chalk.yellow,
  running: chalk.yellow,
  partial: chalk.yellow,
  succeeded: chalk.green,
  failed: chalk.red,
  cancelling: chalk.magenta,
  cancelled: chalk.magenta,
  purged: chalk.gray,
};

const TERMINAL_STATUSES = new Set<Job["status"]>([
  "succeeded",
  "failed",
  "cancelled",
  "purged",
]);

export function formatJobLog(log: JobLog): string {
  const level = log.level.toUpperCase().padEnd(5);
  const color =
    log.level === "error"
      ? chalk.red
      : log.level === "warn"
        ? chalk.yellow
        : chalk.gray;
  return `${chalk.gray(log.createdAt)} ${color(level)} ${chalk.cyan(log.event.padEnd(8))} ${log.message}`;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function registerJobs(program: Command): void {
  const jobs = program
    .command("jobs")
    .alias("job")
    .description("submit and monitor design jobs");

  jobs
    .command("submit")
    .description("submit a new design job")
    .requiredOption("--project <slug>", "project slug")
    .option(
      "--tools <list>",
      "single runnable tool slug (e.g. boltzgen)",
      "boltzgen",
    )
    .requiredOption("--target <pdb>", "target PDB id or uploaded object key")
    .option(
      "--hotspots <list>",
      "comma-separated hotspot residues (e.g. A:42,A:87)",
    )
    .option("--name <name>", "human-readable job name")
    .option("--num-designs <n>", "number of designs to generate", "1")
    .action(
      async (
        opts: {
          project: string;
          tools: string;
          target: string;
          hotspots?: string;
          name?: string;
          numDesigns: string;
        },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);
        const tools = opts.tools.split(",").map((s) => s.trim()).filter(Boolean);
        if (tools.length !== 1) {
          fail("the API currently accepts one tool per job; submit pipeline steps separately");
        }
        const numDesigns = Number(opts.numDesigns) || 1;
        const projectId = await resolveProjectId(client, opts.project);
        const payload = {
          toolId: tools[0],
          request: {
            targetPdb: opts.target,
            hotspots: parseHotspots(opts.hotspots),
            seeds: Array.from({ length: numDesigns }, (_value, index) => index + 1),
            numDesigns,
            toolParams: {
              projectId,
              ...(opts.name ? { name: opts.name } : {}),
            },
          },
        };
        const spin = root.json ? null : ora("submitting job").start();
        const res = await client.mutate<Job>("jobs.submit", payload);
        spin?.stop();
        if (!res.ok) fail(res.error ?? "submit failed");
        if (root.json) return printJson(res.data);
        ok(
          `submitted ${chalk.bold(res.data?.id ?? "?")} -> ${STATUS_COLOR[res.data?.status ?? "queued"](res.data?.status ?? "queued")}`,
        );
      },
    );

  jobs
    .command("ls")
    .alias("list")
    .description("list jobs (optionally filtered by project or status)")
    .option("--status <status>", "filter by status")
    .option("--limit <n>", "max rows", "50")
    .action(
      async (
        opts: { status?: string; limit: string },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);
        const res = await client.query<{ items: Job[] }>("jobs.list", {
          status: opts.status,
          limit: Number(opts.limit) || 50,
        });
        if (!res.ok) fail(res.error ?? "list failed");
        const list = res.data?.items ?? [];
        if (root.json) return printJson(list);
        if (list.length === 0) {
          process.stdout.write(chalk.gray("(no jobs)\n"));
          return;
        }
        printTable(
          ["ID", "TOOL", "STATUS", "DESIGNS", "SUBMITTED"],
          list.map((j) => [
            j.id.slice(0, 12),
            j.toolId,
            STATUS_COLOR[j.status](j.status),
            `${j.completedDesigns}/${j.numDesigns}`,
            j.submittedAt.slice(0, 16).replace("T", " "),
          ]),
        );
      },
    );

  jobs
    .command("status <id>")
    .description("show job status")
    .action(async (id: string, _opts, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      const res = await client.query<Job>("jobs.get", { id });
      if (!res.ok) fail(res.error ?? "not found");
      if (root.json) return printJson(res.data);
      const j = res.data!;
      process.stdout.write(
        `${chalk.bold(j.id)}\n` +
          `  status:   ${STATUS_COLOR[j.status](j.status)}\n` +
          `  tool:     ${j.toolId}\n` +
          `  designs:  ${j.completedDesigns}/${j.numDesigns}\n` +
          `  submitted:${j.submittedAt}\n` +
          `  finished: ${j.finishedAt ?? "-"}\n` +
          (j.errorMessage ? `  ${chalk.red("error:")}    ${j.errorMessage}\n` : ""),
      );
    });

  jobs
    .command("cancel <id>")
    .description("cancel a running or queued job")
    .action(async (id: string, _opts, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      const res = await client.mutate("jobs.cancel", { jobId: id });
      if (!res.ok) fail(res.error ?? "cancel failed");
      if (root.json) return printJson({ ok: true, id });
      ok(`cancelled ${id}`);
    });

  jobs
    .command("logs <id>")
    .description("print job logs")
    .option("-f, --follow", "stream logs as they arrive")
    .action(async (id: string, opts: { follow?: boolean }, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      const seen = new Set<string>();
      let after: string | undefined;

      while (true) {
        const res = await client.query<{ items: JobLog[] }>("jobs.logs", {
          id,
          limit: 500,
          ...(after ? { after } : {}),
        });
        if (!res.ok) fail(res.error ?? "failed to read job logs");
        const fresh = (res.data?.items ?? []).filter((log) => !seen.has(log.id));
        for (const log of fresh) seen.add(log.id);

        if (root.json) {
          if (opts.follow) {
            for (const log of fresh) {
              process.stdout.write(JSON.stringify(log) + "\n");
            }
          } else {
            printJson(fresh);
          }
        } else if (fresh.length === 0 && !opts.follow) {
          process.stdout.write(chalk.gray("(no logs)\n"));
        } else {
          for (const log of fresh) process.stdout.write(formatJobLog(log) + "\n");
        }

        if (!opts.follow) return;
        const latest = fresh.at(-1);
        if (latest) after = latest.createdAt;

        const status = await client.query<Job>("jobs.get", { id });
        if (!status.ok) fail(status.error ?? "failed to read job status");
        if (status.data && TERMINAL_STATUSES.has(status.data.status) && fresh.length === 0) {
          return;
        }
        await wait(1_000);
      }
    });
}

export function parseHotspots(value?: string): Array<{ chain: string; residues: number[] }> {
  if (!value) return [];
  const grouped = new Map<string, number[]>();
  for (const entry of value.split(",")) {
    const match = /^([A-Za-z0-9]):(\d+)$/.exec(entry.trim());
    if (!match) fail(`invalid hotspot '${entry}'; expected A:42`);
    const chain = match[1]!;
    const residues = grouped.get(chain) ?? [];
    residues.push(Number(match[2]));
    grouped.set(chain, residues);
  }
  return Array.from(grouped, ([chain, residues]) => ({ chain, residues }));
}
