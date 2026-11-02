/**
 * Namespaced re-exports of Prisma-generated model + enum types.
 *
 * Consumers should import from `@papercrane/db` and use these namespaced names
 * so application code isn't directly coupled to the generated symbols.
 *
 *   import type { Db } from "@papercrane/db";
 *   const job: Db.Job = ...;
 */
import type {
  Organization,
  User,
  OrgMember,
  Project,
  Target,
  Job,
  Design,
  ApiKey,
  UsageSeed,
  Subscription,
  FeatureFlag,
  Tool,
  BenchmarkRun,
  BenchmarkSubmission,
  OrgTier,
  OrgRole,
  JobStatus,
  GpuBackend,
  SubscriptionStatus,
  ToolCategory,
  ToolTier,
  BenchmarkRunStatus,
  BenchmarkTrigger,
  BenchmarkSubmissionStatus,
} from "@prisma/client";

// eslint-disable-next-line @typescript-eslint/no-namespace
export namespace Db {
  // Models
  export type Org = Organization;
  export type OrgMemberRow = OrgMember;
  export type UserRow = User;
  export type ProjectRow = Project;
  export type TargetRow = Target;
  export type JobRow = Job;
  export type DesignRow = Design;
  export type ApiKeyRow = ApiKey;
  export type UsageSeedRow = UsageSeed;
  export type SubscriptionRow = Subscription;
  export type FeatureFlagRow = FeatureFlag;
  export type ToolRow = Tool;
  export type BenchmarkRunRow = BenchmarkRun;
  export type BenchmarkSubmissionRow = BenchmarkSubmission;

  // Enums (re-exported as types; runtime values live on Prisma.*)
  export type Tier = OrgTier;
  export type Role = OrgRole;
  export type JobState = JobStatus;
  export type Gpu = GpuBackend;
  export type SubState = SubscriptionStatus;
  export type ToolCat = ToolCategory;
  export type ToolAccess = ToolTier;
  export type BenchRunState = BenchmarkRunStatus;
  export type BenchTrigger = BenchmarkTrigger;
  export type BenchSubState = BenchmarkSubmissionStatus;
}

// Also export the raw Prisma names for consumers that prefer them.
export type {
  Organization,
  User,
  OrgMember,
  Project,
  Target,
  Job,
  Design,
  ApiKey,
  UsageSeed,
  Subscription,
  FeatureFlag,
  Tool,
  BenchmarkRun,
  BenchmarkSubmission,
  OrgTier,
  OrgRole,
  JobStatus,
  GpuBackend,
  SubscriptionStatus,
  ToolCategory,
  ToolTier,
  BenchmarkRunStatus,
  BenchmarkTrigger,
  BenchmarkSubmissionStatus,
};
