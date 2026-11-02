import { Command } from "commander";
import ora from "ora";
import chalk from "chalk";
import { promises as fs } from "node:fs";
import path from "node:path";
import { ApiClient, requireAuth } from "../lib/api-client.js";
import { fail, ok, printJson, printTable, rootOpts } from "../lib/output.js";
import { resolveProjectId } from "./projects.js";

interface Design {
  id: string;
  jobId: string;
  artifactKey?: string;
  structureUrl?: string;
  sequence?: string;
  metrics: Record<string, unknown>;
  length?: number;
  rank?: number;
}

export function registerDesigns(program: Command): void {
  const designs = program
    .command("designs")
    .alias("design")
    .description("browse and download designs");

  designs
    .command("ls")
    .alias("list")
    .description("list designs (filter by project, job, or quality metrics)")
    .option("--project <slug>", "filter by project")
    .option("--job <id>", "filter by job id")
    .option("--min-iptm <n>", "minimum ipTM", parseFloat)
    .option("--min-ipsae <n>", "minimum ipSAE", parseFloat)
    .option("--limit <n>", "max rows", "50")
    .action(
      async (
        opts: {
          project?: string;
          job?: string;
          minIptm?: number;
          minIpsae?: number;
          limit: string;
        },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);
        if (!opts.project && !opts.job) fail("pass --project or --job");
        const limit = Number(opts.limit) || 50;
        const res = opts.job
          ? await client.query<{ items: Design[] }>("designs.listByJob", {
              jobId: opts.job,
              limit,
            })
          : await client.query<{ items: Design[] }>("designs.listByProject", {
              projectId: await resolveProjectId(client, opts.project!),
              limit,
            });
        if (!res.ok) fail(res.error ?? "list failed");
        const list = (res.data?.items ?? []).filter((design) => {
          const iptm = metric(design, "iptm");
          const ipsae = metric(design, "ipsae");
          return (
            (opts.minIptm === undefined || (iptm !== undefined && iptm >= opts.minIptm)) &&
            (opts.minIpsae === undefined || (ipsae !== undefined && ipsae >= opts.minIpsae))
          );
        });
        if (root.json) return printJson(list);
        if (list.length === 0) {
          process.stdout.write(chalk.gray("(no designs match)\n"));
          return;
        }
        printTable(
          ["ID", "JOB", "RANK", "LEN", "ipTM", "ipSAE", "pLDDT"],
          list.map((d) => [
            d.id.slice(0, 12),
            d.jobId.slice(0, 10),
            String(d.rank ?? "-"),
            String(d.length ?? "-"),
            fmt(metric(d, "iptm")),
            fmt(metric(d, "ipsae")),
            fmt(metric(d, "plddt")),
          ]),
        );
      },
    );

  designs
    .command("download <id>")
    .description("download a design (cif/pdb/fasta)")
    .option("--format <fmt>", "cif | pdb | fasta", "cif")
    .option("--out <dir>", "output directory", ".")
    .action(
      async (
        id: string,
        opts: { format: "cif" | "pdb" | "fasta"; out: string },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);
        const spin = root.json ? null : ora(`downloading ${id}`).start();
        const res = await client.query<Design>("designs.get", { id });
        if (!res.ok || !res.data) {
          spin?.stop();
          fail(res.error ?? "download failed");
        }
        const design = res.data!;
        await fs.mkdir(opts.out, { recursive: true });
        let target: string;
        if (opts.format === "fasta") {
          if (!design.sequence) fail("design has no sequence");
          target = path.resolve(opts.out, `${id}.fasta`);
          await fs.writeFile(target, `>${id}\n${design.sequence}\n`);
        } else if (design.structureUrl) {
          const storedFormat = path.extname(design.artifactKey ?? "").slice(1).toLowerCase();
          if (storedFormat && storedFormat !== opts.format) {
            fail(`design is stored as ${storedFormat}; structure conversion is not available`);
          }
          target = path.resolve(opts.out, `${id}.${storedFormat || opts.format}`);
          const r = await fetch(design.structureUrl);
          if (!r.ok) {
            spin?.stop();
            fail(`presigned fetch failed (${r.status})`);
          }
          const bytes = new Uint8Array(await r.arrayBuffer());
          await fs.writeFile(target, bytes);
        } else {
          spin?.stop();
          fail("design has no persisted structure artifact");
        }
        spin?.stop();
        if (root.json) return printJson({ ok: true, path: target });
        ok(`saved ${chalk.cyan(target)}`);
      },
    );

  designs
    .command("export-fasta")
    .description("export designs as a multi-FASTA file")
    .option("--project <slug>", "filter by project")
    .option("--job <id>", "filter by job id")
    .option("--out <file>", "output file", "designs.fasta")
    .action(
      async (
        opts: { project?: string; job?: string; out: string },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);
        if (!opts.project && !opts.job) fail("pass --project or --job");
        const res = opts.job
          ? await client.query<{ items: Design[] }>("designs.listByJob", {
              jobId: opts.job,
              limit: 500,
            })
          : await client.query<{ items: Design[] }>("designs.listByProject", {
              projectId: await resolveProjectId(client, opts.project!),
              limit: 500,
            });
        if (!res.ok) fail(res.error ?? "list failed");
        const lines: string[] = [];
        for (const d of res.data?.items ?? []) {
          if (!d.sequence) continue;
          lines.push(`>${d.id} job=${d.jobId} iptm=${fmt(metric(d, "iptm"))} ipsae=${fmt(metric(d, "ipsae"))}`);
          lines.push(d.sequence);
        }
        await fs.writeFile(opts.out, lines.join("\n") + "\n");
        if (root.json) return printJson({ ok: true, count: lines.length / 2, path: opts.out });
        ok(`wrote ${lines.length / 2} sequences → ${chalk.cyan(opts.out)}`);
      },
    );
}

function fmt(n: number | undefined): string {
  if (n === undefined || Number.isNaN(n)) return "-";
  return n.toFixed(3);
}

function metric(design: Design, key: string): number | undefined {
  const value = design.metrics[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
