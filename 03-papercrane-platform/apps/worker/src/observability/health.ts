/**
 * Worker health probe.
 *
 * The worker is headless (BullMQ consumer), so we expose a tiny stdlib HTTP
 * server on `PORT_HEALTH` (default 9090) with a single `GET /healthz`. This
 * is what Fly's TCP/HTTP health check and the docker-compose healthcheck
 * point at.
 *
 * Response shape (matches `apps/api/src/observability/health.ts`):
 *   { ok, db, redis, version, uptime_s }
 *
 * - `db` pings Postgres via `prisma.$queryRaw` (`SELECT 1`).
 * - `redis` pings the BullMQ Redis connection via `PING`.
 * - HTTP 503 if any required dep is down.
 *
 * The server is intentionally bare-stdlib `node:http` to keep the worker free
 * of HTTP framework deps. It also means it cannot accidentally serve any
 * other route — `/healthz` is the only path that ever returns a body.
 */
import http, { type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type Redis from 'ioredis';
import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';

export interface WorkerHealthDeps {
  prisma: PrismaClient;
  /**
   * Redis client. Optional in dev-fallback mode — when omitted, the probe
   * reports `redis: false` but does NOT fail the overall check (gated on
   * `devMode`).
   */
  redis?: Redis;
  logger: Logger;
  /** Service version (defaults to env `APP_VERSION` / npm pkg / "0.0.0"). */
  version?: string;
  /** Override default port (env `PORT_HEALTH`, fallback 9090). */
  port?: number;
  /**
   * When true, Redis-down does NOT fail the probe. Set ONLY by the dev
   * fallback path in `server.ts` (NODE_ENV !== 'production' AND Redis
   * ECONNREFUSED). Production callers must leave this undefined/false.
   */
  devMode?: boolean;
}

export interface WorkerHealthBody {
  ok: boolean;
  db: boolean;
  redis: boolean;
  version: string;
  uptime_s: number;
}

export interface WorkerHealthServer {
  /** Underlying http.Server — exposed for tests. */
  server: Server;
  /** Bound port (resolved if 0 was requested). */
  port: number;
  /** Stop accepting connections and close. */
  close: () => Promise<void>;
}

const STARTED_AT_MS = Date.now();

async function pingDb(prisma: PrismaClient): Promise<boolean> {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return true;
  } catch {
    return false;
  }
}

async function pingRedis(redis: Redis): Promise<boolean> {
  try {
    const pong = await redis.ping();
    return pong === 'PONG';
  } catch {
    return false;
  }
}

/**
 * Start the worker health HTTP server. Returns a handle with `.close()` for
 * the shutdown path. The server logs a single ready line and one line per
 * unexpected error — successful probes are not logged (would be too noisy
 * given Fly's once-per-second cadence).
 */
export async function startHealthServer(
  deps: WorkerHealthDeps,
): Promise<WorkerHealthServer> {
  const port = deps.port ?? Number.parseInt(process.env.PORT_HEALTH ?? '9090', 10);
  const version =
    deps.version ?? process.env.APP_VERSION ?? process.env.npm_package_version ?? '0.0.0';

  const server = http.createServer(async (req: IncomingMessage, res: ServerResponse) => {
    if (req.method !== 'GET' || req.url !== '/healthz') {
      res.statusCode = 404;
      res.end();
      return;
    }
    try {
      const [db, redis] = await Promise.all([
        pingDb(deps.prisma),
        deps.redis ? pingRedis(deps.redis) : Promise.resolve(false),
      ]);
      // In dev-fallback mode, treat Redis-down as non-fatal — the in-memory
      // queue is handling jobs. DB is still required even in dev because
      // every code path reads/writes Postgres.
      const ok = deps.devMode ? db : db && redis;
      const body: WorkerHealthBody = {
        ok,
        db,
        redis,
        version,
        uptime_s: Math.floor((Date.now() - STARTED_AT_MS) / 1000),
      };
      res.statusCode = ok ? 200 : 503;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify(body));
    } catch (err) {
      deps.logger.error({ err }, 'healthz handler crashed');
      res.statusCode = 503;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ ok: false, db: false, redis: false, version, uptime_s: 0 }));
    }
  });

  server.on('error', (err) => deps.logger.error({ err }, 'health server error'));

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, () => {
      server.removeListener('error', reject);
      resolve();
    });
  });

  const addr = server.address();
  const boundPort = typeof addr === 'object' && addr ? addr.port : port;
  deps.logger.info({ port: boundPort }, 'health server ready');

  const close = (): Promise<void> =>
    new Promise<void>((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });

  return { server, port: boundPort, close };
}
