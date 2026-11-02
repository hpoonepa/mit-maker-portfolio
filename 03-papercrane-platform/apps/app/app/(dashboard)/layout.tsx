import { headers } from "next/headers";
import { betaGateEnabled } from "@papercrane/types";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { Providers } from "@/app/providers";
import { WhatsNew } from "@/components/beta/WhatsNew";
import { SearchProvider } from "@/components/command/SearchProvider";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { FeedbackWidget } from "@/components/feedback/FeedbackWidget";
import { getSessionUser } from "@/lib/supabase/server";
import { createServerTrpc } from "@/lib/trpc/server";

// 30-day staleness window for the BYOK Modal-credential gate. After this we
// force a re-validation by bouncing the user back through the connect flow
// (Modal tokens can be revoked server-side without our knowledge).
const MODAL_VALIDATION_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export const dynamic = "force-dynamic";

/**
 * Dashboard shell. Middleware already guards `/app/*`, but we re-verify in
 * the RSC layout for defense-in-depth.
 *
 * Loads the current period usage (best-effort) so the TopBar's seed meter
 * shows live numbers. Failures degrade gracefully to placeholders rather
 * than crashing the layout.
 */
export default async function DashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  const user = await getSessionUser();
  if (!user) {
    redirect("/login");
  }

  // Authentication and private-beta admission are separate guarantees.
  // Fail closed while the gate is active so a directly-created Supabase
  // account cannot bypass invite consumption by skipping the callback UI.
  if (betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE)) {
    const trpc = await createServerTrpc();
    const access = await trpc.beta.accessStatus.query();
    if (!access.granted) {
      redirect(
        "/signup?error=A%20valid%20beta%20invite%20is%20required%20for%20new%20accounts.",
      );
    }
  }

  // Resolve current path for the gate exception list. (dashboard) layout
  // doesn't run for /onboarding/* or /admin/*: but the next-url header is
  // read defensively in case the route group ever changes.
  const hdrs = await headers();
  const pathname =
    hdrs.get("x-invoke-path") ??
    hdrs.get("x-pathname") ??
    hdrs.get("next-url") ??
    "";
  const isOnboardingRoute = pathname.startsWith("/onboarding");
  const isAdminRoute = pathname.startsWith("/admin");
  const byokRequired = process.env.MODAL_BYOK_REQUIRED === "true";

  let org = {
    slug: "default",
    name: deriveOrgName(user.email ?? "you"),
  };
  let usage = { consumed: 0, included: 1000 };

  try {
    const trpc = await createServerTrpc();
    // BYOK Modal-credential gate. Signed-in users without a fresh
    // ModalCredential row get bounced to the connect flow. Skip when the
    // user is on an exception route or the env-var escape hatch is set.
    if (byokRequired && !isOnboardingRoute && !isAdminRoute) {
      try {
        const status = await trpc.modalAccounts.status.query();
        const validatedAt = status.lastValidatedAt
          ? new Date(status.lastValidatedAt).getTime()
          : 0;
        const stale =
          !validatedAt ||
          Date.now() - validatedAt > MODAL_VALIDATION_TTL_MS;
        if (!status.connected || stale) {
          redirect("/onboarding/connect-modal");
        }
      } catch (err) {
        // `redirect()` throws a NEXT_REDIRECT: must propagate, not swallow.
        if ((err as { digest?: string })?.digest?.startsWith("NEXT_REDIRECT")) {
          throw err;
        }
        // Other failures (auth, migration not applied) degrade gracefully:
        // we'd rather render the dashboard than 500 the whole app.
      }
    }
    const u = await trpc.usage.getCurrentPeriodUsage.query();
    usage = {
      consumed: u.seedsConsumed ?? 0,
      included: u.seedsIncluded ?? 1000,
    };
    if (u.orgSlug) {
      // Pretty up the slug as a fallback name. Real org name will land
      // once `orgs.current` ships; this keeps the topbar honest in the
      // meantime (papercrane-demo-lab → "Papercrane Demo Lab").
      const slug: string = u.orgSlug;
      const pretty = slug
        .split("-")
        .map((w) => (w.length > 0 ? w[0]!.toUpperCase() + w.slice(1) : w))
        .join(" ");
      org = { slug, name: pretty };
    }
  } catch {
    // Best-effort. Auth, network, or migration-not-yet-applied: keep going.
  }

  const displayName =
    (user.user_metadata?.full_name as string | undefined) ??
    (user.user_metadata?.name as string | undefined);

  return (
    <Providers>
      <SearchProvider>
        <div className="min-h-screen bg-paper text-ink">
          <DashboardShell
            userEmail={user.email ?? "unknown@papercrane.bio"}
            userName={displayName}
            orgSlug={org.slug}
            orgName={org.name}
            seedsConsumed={usage.consumed}
            seedsIncluded={usage.included}
          >
            {children}
          </DashboardShell>
          <FeedbackWidget
            userInfo={{
              userId: user.id,
              orgSlug: org.slug,
            }}
          />
          {/* Pops on first dashboard load if there's a changelog entry the
              user hasn't acknowledged yet. Self-contained: reads its own
              cursor via tRPC. */}
          <WhatsNew />
        </div>
      </SearchProvider>
    </Providers>
  );
}

function deriveOrgName(email: string): string {
  const [local, domain] = email.split("@");
  if (domain && !["gmail.com", "outlook.com", "yahoo.com"].includes(domain)) {
    const short = domain.split(".")[0] ?? "";
    return short.charAt(0).toUpperCase() + short.slice(1);
  }
  return (local ?? "Workspace").charAt(0).toUpperCase() + (local ?? "").slice(1);
}
