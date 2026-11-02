/**
 * Root tRPC router for the Paper Crane API.
 *
 * The Next.js dashboard imports this directly as a tRPC client; the API
 * app wraps the same tree with `trpc-to-openapi` to emit REST (plan 01
 * §2). Adding a router here therefore registers it in both places.
 */
import { router } from '../trpc.js';
import { healthRouter } from './health.js';
import { projectsRouter } from './projects.js';
import { targetsRouter } from './targets.js';
import { jobsRouter } from './jobs.js';
import { designsRouter } from './designs.js';
import { usageRouter } from './usage.js';
import { toolsRouter } from './tools.js';
import { webhooksRouter } from './webhooks.js';
import { keysRouter } from './keys.js';
import { billingRouter } from './billing.js';
import { auditRouter } from './audit.js';
import { onboardingRouter } from './onboarding.js';
import { membersRouter } from './members.js';
import { notificationsRouter } from './notifications.js';
import { searchRouter } from './search.js';
import { dashboardRouter } from './dashboard.js';
import { integrationsRouter } from './integrations.js';
import { annotationsRouter } from './annotations.js';
import { feedbackRouter } from './feedback.js';
import { betaRouter } from './beta.js';
import { modalAccountsRouter } from './modalAccounts.js';

export const appRouter = router({
  health: healthRouter,
  projects: projectsRouter,
  targets: targetsRouter,
  jobs: jobsRouter,
  designs: designsRouter,
  usage: usageRouter,
  tools: toolsRouter,
  webhooks: webhooksRouter,
  keys: keysRouter,
  billing: billingRouter,
  audit: auditRouter,
  onboarding: onboardingRouter,
  members: membersRouter,
  notifications: notificationsRouter,
  search: searchRouter,
  dashboard: dashboardRouter,
  integrations: integrationsRouter,
  annotations: annotationsRouter,
  feedback: feedbackRouter,
  beta: betaRouter,
  modalAccounts: modalAccountsRouter,
});

export type AppRouter = typeof appRouter;
