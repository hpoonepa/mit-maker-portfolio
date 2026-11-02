import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { parse, stringify } from "smol-toml";

export interface PapercraneConfig {
  apiKey?: string;
  apiUrl?: string;
  email?: string;
  org?: string;
  tier?: string;
}

export function configDir(): string {
  // Honor XDG_CONFIG_HOME, fall back to ~/.config/papercrane.
  const xdg = process.env.XDG_CONFIG_HOME;
  const base = xdg && xdg.length > 0 ? xdg : path.join(os.homedir(), ".config");
  return path.join(base, "papercrane");
}

export function configPath(): string {
  return path.join(configDir(), "config.toml");
}

export async function loadConfig(): Promise<PapercraneConfig> {
  try {
    const raw = await fs.readFile(configPath(), "utf8");
    const parsed = parse(raw) as unknown as PapercraneConfig;
    return parsed ?? {};
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw err;
  }
}

export async function saveConfig(cfg: PapercraneConfig): Promise<void> {
  await fs.mkdir(configDir(), { recursive: true, mode: 0o700 });
  const toml = stringify(cfg as Record<string, unknown>);
  await fs.writeFile(configPath(), toml, { mode: 0o600 });
  // Re-chmod in case umask widened it.
  await fs.chmod(configPath(), 0o600);
}

export async function clearConfig(): Promise<void> {
  try {
    await fs.unlink(configPath());
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
  }
}

export function resolveApiKey(cfg: PapercraneConfig): string | undefined {
  return process.env.PAPERCRANE_API_KEY ?? cfg.apiKey;
}
