import type { Prisma, PrismaClient } from '@papercrane/db';
import type { JobEvent } from '@papercrane/jobs';
import type { Logger } from '@papercrane/observability';

export interface PersistedJobLog {
  level: 'info' | 'warn' | 'error';
  event: JobEvent['type'];
  message: string;
  metadata: Record<string, unknown>;
}

const MAX_MESSAGE_LENGTH = 4_000;

/** Remove common credential forms before provider errors reach durable logs. */
export function redactJobLogMessage(message: string): string {
  return message
    .replace(/\b(Bearer\s+)[^\s,;]+/gi, '$1[REDACTED]')
    .replace(
      /\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+/gi,
      '$1=[REDACTED]',
    )
    .replace(/\bpc_[A-Za-z0-9_-]{8,}\b/g, 'pc_[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, 'sk-[REDACTED]')
    .replace(/([a-z][a-z0-9+.-]*:\/\/)[^/@\s]+@/gi, '$1[REDACTED]@')
    .slice(0, MAX_MESSAGE_LENGTH);
}

export function jobEventToLog(event: JobEvent): PersistedJobLog {
  switch (event.type) {
    case 'status':
      return {
        level: event.status === 'failed' ? 'error' : 'info',
        event: event.type,
        message: `Job status: ${event.status}`,
        metadata: { status: event.status },
      };
    case 'progress':
      return {
        level: 'info',
        event: event.type,
        message: `Progress: ${event.completed}/${event.total} designs`,
        metadata: { completed: event.completed, total: event.total },
      };
    case 'design':
      return {
        level: 'info',
        event: event.type,
        message: `Design completed for seed ${event.seed}`,
        metadata: { designId: event.designId, seed: event.seed },
      };
    case 'error':
      return {
        level: 'error',
        event: event.type,
        message: redactJobLogMessage(event.message),
        metadata: { retryable: event.retryable },
      };
  }
}

/** Persistence is best-effort so an observability outage cannot kill compute. */
export async function persistJobEvent(
  prisma: PrismaClient,
  logger: Logger,
  jobId: string,
  event: JobEvent,
): Promise<void> {
  const log = jobEventToLog(event);
  try {
    await prisma.jobLog.create({
      data: {
        jobId,
        level: log.level,
        event: log.event,
        message: log.message,
        metadata: log.metadata as Prisma.InputJsonValue,
      },
    });
  } catch (err) {
    logger.error({ jobId, err, event: event.type }, 'failed to persist job log');
  }
}
