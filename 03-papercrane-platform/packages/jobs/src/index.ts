/**
 * @papercrane/jobs — canonical job state machine, event schemas, and
 * retry/queue helpers for the Paper Crane orchestrator.
 *
 * See `docs/plans/01-core-platform.md` §5 for the full state diagram
 * and design rationale.
 */

// Status + terminal-state helpers
export {
  JOB_STATUSES,
  TERMINAL_STATUSES,
  isTerminal,
  canTransition,
  type JobStatus,
} from './status';

// Transition table + guard
export {
  TRANSITIONS,
  transition,
  IllegalTransitionError,
} from './transitions';

// Event builders + schemas
export {
  statusEvent,
  designEvent,
  progressEvent,
  errorEvent,
  JobEventSchema,
  JobStatusSchema,
  MetricsSchema,
  StatusEventSchema,
  DesignEventSchema,
  ProgressEventSchema,
  ErrorEventSchema,
  type JobEvent,
  type StatusEvent,
  type DesignEvent,
  type ProgressEvent,
  type ErrorEvent,
  type Metrics,
} from './events';

// Retry policy
export {
  shouldRetry,
  backoffSeconds,
  MAX_RETRIES,
  INFRA_ERROR_CODES,
  USER_ERROR_CODES,
  type JobError,
  type JobErrorCode,
  type InfraErrorCode,
  type UserErrorCode,
} from './retry';

// BullMQ queue names
export {
  jobQueueName,
  JOB_QUEUE_NAMES,
  ALL_JOB_QUEUE_NAMES,
  TIERS,
  type Tier,
  type JobQueueName,
} from './queue';

// Wire encoding
export {
  serializeEvent,
  deserializeEvent,
  tryDeserializeEvent,
} from './serde';

// Job spec + adapter contract
export {
  JobSpecSchema,
  ToolChainStageSchema,
  type JobSpec,
  type ToolChainStage,
  type ToolInput,
  type ToolOutput,
  type ToolAdapter,
} from './types';
