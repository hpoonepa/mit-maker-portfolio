import chalk from "chalk";
import Table from "cli-table3";

export interface RootOpts {
  json?: boolean;
  apiUrl?: string;
}

export function rootOpts(cmd: { parent?: { opts?: () => RootOpts } | null }): RootOpts {
  return cmd.parent?.opts?.() ?? {};
}

export function printJson(value: unknown): void {
  process.stdout.write(JSON.stringify(value, null, 2) + "\n");
}

export function printTable(headers: string[], rows: string[][]): void {
  const t = new Table({
    head: headers.map((h) => chalk.bold.cyan(h)),
    style: { head: [], border: ["gray"] },
  });
  for (const r of rows) t.push(r);
  process.stdout.write(t.toString() + "\n");
}

export function ok(msg: string): void {
  process.stdout.write(chalk.green("✓ ") + msg + "\n");
}

export function info(msg: string): void {
  process.stdout.write(chalk.cyan("• ") + msg + "\n");
}

export function warn(msg: string): void {
  process.stderr.write(chalk.yellow("! ") + msg + "\n");
}

export function fail(msg: string): never {
  process.stderr.write(chalk.red("✗ ") + msg + "\n");
  process.exit(1);
}
