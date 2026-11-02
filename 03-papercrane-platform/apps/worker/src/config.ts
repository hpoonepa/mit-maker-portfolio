/**
 * Worker configuration loaded from env.
 *
 * The worker is expected to run on Fly.io with secrets injected via
 * `fly secrets set`. For local dev, `.env` at the monorepo root is loaded
 * by `tsx` via `--env-file`.
 */

import type { Tier } from '@papercrane/jobs';

export interface WorkerConfig {
  redisUrl: string;
  databaseUrl: string;
  concurrency: Record<Tier, number>;
  logLevel: string;
  nodeEnv: 'development' | 'staging' | 'production' | 'test';
  providers: {
    modal: {
      tokenId?: string;
      tokenSecret?: string;
      workspace?: string;
      environment?: string;
    };
    vastai: { apiKey?: string };
    runpod: { apiKey?: string };
  };
  /** Default retention in days when a job's org does not specify. */
  defaultRetentionDays: number;
  /** How often the retention cron runs, in seconds. */
  retentionIntervalSeconds: number;
  /** Active-job heartbeat age after which an attempt is fenced and retried. */
  jobHeartbeatTimeoutSeconds: number;
  /** How often to scan for expired worker heartbeats. */
  stuckJobSweepIntervalSeconds: number;
  /** Seconds to wait for in-flight jobs to drain on SIGTERM. */
  shutdownTimeoutSeconds: number;
  /** Max concurrent webhook deliveries across the worker instance. */
  webhookConcurrency: number;
  /** Per-request HTTP timeout (ms) for outbound webhook POSTs. */
  webhookTimeoutMs: number;
}

function readInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(`env ${name} must be a non-negative integer, got: ${raw}`);
  }
  return n;
}

function readString(name: string, fallback?: string): string {
  const v = process.env[name];
  if (v && v.length > 0) return v;
  if (fallback !== undefined) return fallback;
  throw new Error(`env ${name} is required`);
}

export function loadConfig(): WorkerConfig {
  return {
    redisUrl: readString('REDIS_URL', 'redis://localhost:6379'),
    databaseUrl: readString('DATABASE_URL', 'postgresql://localhost:5432/papercrane'),
    concurrency: {
      free: readInt('WORKER_CONCURRENCY_FREE', 5),
      pro: readInt('WORKER_CONCURRENCY_PRO', 20),
      frontier: readInt('WORKER_CONCURRENCY_FRONTIER', 50),
    },
    logLevel: readString('LOG_LEVEL', 'info'),
    nodeEnv: (process.env.NODE_ENV as WorkerConfig['nodeEnv']) ?? 'development',
    providers: {
      modal: {
        tokenId: process.env.MODAL_TOKEN_ID,
        tokenSecret: process.env.MODAL_TOKEN_SECRET,
        workspace: process.env.MODAL_WORKSPACE,
        environment: process.env.MODAL_ENVIRONMENT,
      },
      vastai: { apiKey: process.env.VASTAI_API_KEY },
      runpod: { apiKey: process.env.RUNPOD_API_KEY },
    },
    defaultRetentionDays: readInt('DEFAULT_RETENTION_DAYS', 7),
    retentionIntervalSeconds: readInt('RETENTION_INTERVAL_SECONDS', 60 * 60 * 24),
    jobHeartbeatTimeoutSeconds: readInt('JOB_HEARTBEAT_TIMEOUT_SECONDS', 20 * 60),
    stuckJobSweepIntervalSeconds: readInt('STUCK_JOB_SWEEP_INTERVAL_SECONDS', 60),
    shutdownTimeoutSeconds: readInt('SHUTDOWN_TIMEOUT_SECONDS', 30),
    webhookConcurrency: readInt('WEBHOOK_CONCURRENCY', 10),
    webhookTimeoutMs: readInt('WEBHOOK_TIMEOUT_MS', 10_000),
  };
}
