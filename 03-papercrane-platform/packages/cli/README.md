# @papercrane/cli

Paper Crane CLI — submit binder design jobs, monitor runs, and manage projects from your terminal.

## Install

```bash
# npm (global)
npm i -g @papercrane/cli

# Homebrew (once tap is published)
brew tap papercrane/tap
brew install papercrane
```

## Quick start

```bash
papercrane login                            # paste API key or OAuth via browser
papercrane whoami                           # Logged in as you@papercrane.bio (Org: …, Tier: Pro)

papercrane projects ls
papercrane projects create "GLP-1R Project"

papercrane jobs submit \
  --project glp1r \
  --tools boltzgen \
  --target 6X1A \
  --hotspots A:42,A:87 \
  --num-designs 1

papercrane jobs status <job-id>
papercrane designs ls --project glp1r --min-iptm 0.7
papercrane designs download <design-id> --format cif --out ./out
papercrane designs export-fasta --project glp1r --out glp1r.fasta
```

## Auth

The API key is stored at `~/.config/papercrane/config.toml` (chmod 600). Override per-command with the `PAPERCRANE_API_KEY` env var, or point at a different deployment with `PAPERCRANE_API_URL` / `--api-url`.

## Flags

- `--json` on any command emits machine-readable JSON.
- `--help` is wired up on every subcommand.

Job submission currently accepts one runnable tool per job. Durable worker
logs are exposed through `jobs logs <id>`; add `--follow` to poll until the
job reaches a terminal state.

## Develop

```bash
pnpm --filter @papercrane/cli build
pnpm --filter @papercrane/cli exec papercrane whoami
```
