import { Command } from "commander";
import ora from "ora";
import chalk from "chalk";
import prompts from "prompts";
import { ApiClient, requireAuth } from "../lib/api-client.js";
import { fail, ok, printJson, printTable, rootOpts } from "../lib/output.js";

interface Project {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  createdAt?: string;
  jobCount?: number;
}

export function registerProjects(program: Command): void {
  const projects = program
    .command("projects")
    .alias("project")
    .description("manage Paper Crane projects");

  projects
    .command("ls")
    .alias("list")
    .description("list your projects")
    .action(async (_opts, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      const spin = root.json ? null : ora("fetching projects").start();
      const res = await client.query<{ items: Project[] }>("projects.list", {});
      spin?.stop();
      if (!res.ok) fail(res.error ?? "failed to list projects");
      const list = res.data?.items ?? [];
      if (root.json) return printJson(list);
      if (list.length === 0) {
        process.stdout.write(chalk.gray("(no projects yet)\n"));
        return;
      }
      printTable(
        ["SLUG", "NAME", "DESCRIPTION", "CREATED"],
        list.map((p) => [
          p.slug,
          p.name,
            p.description ?? "-",
          (p.createdAt ?? "").slice(0, 10),
        ]),
      );
    });

  projects
    .command("create [name]")
    .description("create a new project")
    .option("--description <text>", "project description")
    .option("--slug <slug>", "URL-safe slug")
    .action(
      async (
        name: string | undefined,
        opts: { description?: string; slug?: string },
        cmd,
      ) => {
        const root = rootOpts(cmd.parent ?? cmd);
        const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
        requireAuth(client);

        if (!name && !root.json) {
          const ans = await prompts({
            type: "text",
            name: "name",
            message: "Project name",
          });
          name = ans.name as string | undefined;
        }
        if (!name) fail("project name required");

        const spin = root.json ? null : ora("creating project").start();
        const slug = opts.slug ?? slugify(name!);
        if (!slug) fail("project slug must contain letters or numbers");
        const res = await client.mutate<Project>("projects.create", {
          name,
          description: opts.description,
          slug,
        });
        spin?.stop();
        if (!res.ok) fail(res.error ?? "failed to create project");
        if (root.json) return printJson(res.data);
        ok(
          `created ${chalk.bold(res.data?.name ?? name)} (slug: ${chalk.cyan(res.data?.slug ?? "?")})`,
        );
      },
    );

  projects
    .command("show <id-or-slug>")
    .description("show project details")
    .action(async (idOrSlug: string, _opts, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      const id = await resolveProjectId(client, idOrSlug);
      const res = await client.query<Project>("projects.get", { id });
      if (!res.ok) fail(res.error ?? "not found");
      if (root.json) return printJson(res.data);
      const p = res.data!;
      process.stdout.write(
        `${chalk.bold(p.name)}  ${chalk.gray(p.id)}\n` +
          `  slug:    ${p.slug}\n` +
          `  details: ${p.description ?? "-"}\n` +
          `  created: ${(p.createdAt ?? "").slice(0, 10)}\n`,
      );
    });

  projects
    .command("delete <id-or-slug>")
    .alias("rm")
    .description("delete a project (irreversible)")
    .option("-y, --yes", "skip confirmation")
    .action(async (idOrSlug: string, opts: { yes?: boolean }, cmd) => {
      const root = rootOpts(cmd.parent ?? cmd);
      const client = await ApiClient.fromEnv({ apiUrl: root.apiUrl });
      requireAuth(client);
      if (!opts.yes && !root.json) {
        const ans = await prompts({
          type: "confirm",
          name: "go",
          message: `Delete project ${chalk.bold(idOrSlug)}?`,
          initial: false,
        });
        if (!ans.go) return;
      }
      const id = await resolveProjectId(client, idOrSlug);
      const res = await client.mutate("projects.delete", { id });
      if (!res.ok) fail(res.error ?? "failed to delete");
      if (root.json) return printJson({ ok: true, id });
      ok(`deleted ${idOrSlug}`);
    });
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export async function resolveProjectId(
  client: ApiClient,
  idOrSlug: string,
): Promise<string> {
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(idOrSlug)) {
    return idOrSlug;
  }
  const res = await client.query<{ items: Project[] }>("projects.list", {
    limit: 200,
  });
  if (!res.ok) throw new Error(res.error ?? "failed to resolve project");
  const project = res.data?.items.find((item) => item.slug === idOrSlug);
  if (!project) throw new Error(`project not found: ${idOrSlug}`);
  return project.id;
}
