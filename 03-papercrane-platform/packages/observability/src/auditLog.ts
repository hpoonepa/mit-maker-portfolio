/**
 * Audit-log helper.
 *
 * Every privileged mutation in `apps/api` and the worker should funnel
 * through `logAuditEvent`. The helper is deliberately forgiving: if the
 * insert fails (DB down, bad RLS, etc.) we log and return `null` rather
 * than throwing — audit logging must never break the primary action.
 *
 * Allowed action ids mirror the `AuditAction` Prisma enum. The runtime
 * guard here is a second line of defence: TypeScript catches typos, and
 * this rejects anything exotic that slips through `any`.
 */

export const AUDIT_ACTIONS = [
  'api_key.created',
  'api_key.revoked',
  'api_key.rotated',
  'webhook.created',
  'webhook.deleted',
  'webhook.secret_rotated',
  'member.invited',
  'member.removed',
  'member.role_changed',
  'subscription.upgraded',
  'subscription.downgraded',
  'subscription.cancelled',
  'job.cancelled',
  'tool_license.acknowledged',
  'org.created',
  'org.settings_updated',
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];

const ALLOWED = new Set<string>(AUDIT_ACTIONS);

/** Minimal shape — either a Prisma client or a Prisma transaction client. */
export interface AuditPrismaLike {
  auditLog: {
    create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
  };
}

/** Request-like object for IP / user-agent extraction. */
export interface RequestLike {
  headers?: Record<string, string | string[] | undefined>;
  ip?: string | null;
  socket?: { remoteAddress?: string | null };
}

export interface LogAuditEventInput {
  orgId: string;
  userId?: string | null;
  action: AuditAction;
  resourceType?: string | null;
  resourceId?: string | null;
  metadata?: Record<string, unknown> | null;
  req?: RequestLike;
  /** Explicit overrides — bypass `req` extraction when supplied. */
  ipAddress?: string | null;
  userAgent?: string | null;
}

export interface RequestMeta {
  ipAddress: string | null;
  userAgent: string | null;
}

function firstHeader(
  h: Record<string, string | string[] | undefined> | undefined,
  name: string,
): string | null {
  if (!h) return null;
  const v = h[name] ?? h[name.toLowerCase()];
  if (Array.isArray(v)) return v[0] ?? null;
  return v ?? null;
}

/**
 * Resolve the caller IP and user-agent from a request-like object.
 *
 *   - `x-forwarded-for` takes precedence (leftmost entry, trimmed).
 *   - falls back to `req.ip`, then `req.socket.remoteAddress`.
 *   - `user-agent` header becomes `userAgent` verbatim.
 */
export function extractRequestMeta(req: RequestLike | undefined): RequestMeta {
  if (!req) return { ipAddress: null, userAgent: null };

  const xff = firstHeader(req.headers, 'x-forwarded-for');
  let ip: string | null = null;
  if (xff) {
    const first = xff.split(',')[0];
    ip = first ? first.trim() : null;
  }
  if (!ip && req.ip) ip = req.ip;
  if (!ip && req.socket?.remoteAddress) ip = req.socket.remoteAddress;

  const ua = firstHeader(req.headers, 'user-agent');

  return { ipAddress: ip ?? null, userAgent: ua ?? null };
}

/**
 * Append a single row to the `audit_logs` table.
 *
 * Returns the created row on success, or `null` if the insert failed or
 * the action id was rejected. Errors are swallowed so call sites can
 * invoke this inline without try/catch around their own logic.
 */
export async function logAuditEvent(
  prisma: AuditPrismaLike,
  input: LogAuditEventInput,
): Promise<unknown | null> {
  if (!ALLOWED.has(input.action)) {
    // Refuse to write unknown actions — prevents typos from polluting
    // the immutable log.
    return null;
  }

  const meta =
    input.ipAddress !== undefined || input.userAgent !== undefined
      ? { ipAddress: input.ipAddress ?? null, userAgent: input.userAgent ?? null }
      : extractRequestMeta(input.req);

  try {
    return await prisma.auditLog.create({
      data: {
        orgId: input.orgId,
        userId: input.userId ?? null,
        action: input.action,
        resourceType: input.resourceType ?? null,
        resourceId: input.resourceId ?? null,
        metadata: input.metadata ?? null,
        ipAddress: meta.ipAddress,
        userAgent: meta.userAgent,
      },
    });
  } catch {
    // Intentionally swallow — callers should not fail their mutation
    // because the audit row couldn't be written. The DB layer logs via
    // Prisma middleware; a higher-level observer can correlate.
    return null;
  }
}
