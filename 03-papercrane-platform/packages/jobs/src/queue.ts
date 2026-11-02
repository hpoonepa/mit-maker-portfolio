/**
 * BullMQ queue names, partitioned per-tier.
 *
 * Plan 03 §7 describes weighted fair queueing: free/pro/frontier each get
 * their own queue so that a Frontier 50K-seed job never starves a Pro
 * customer's 500-seed job.
 */

export const TIERS = ['free', 'pro', 'frontier'] as const;
export type Tier = (typeof TIERS)[number];

export const JOB_QUEUE_NAMES = {
  free: 'jobs-free',
  pro: 'jobs-pro',
  frontier: 'jobs-frontier',
} as const satisfies Record<Tier, string>;

export type JobQueueName = (typeof JOB_QUEUE_NAMES)[Tier];

/** Returns the BullMQ queue name for a given billing tier. */
export function jobQueueName(tier: Tier): JobQueueName {
  return JOB_QUEUE_NAMES[tier];
}

/** All queue names, useful for workers that consume from every tier. */
export const ALL_JOB_QUEUE_NAMES: readonly JobQueueName[] =
  TIERS.map(jobQueueName);
