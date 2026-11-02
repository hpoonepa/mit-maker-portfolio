import { redirect } from "next/navigation";
import { getSessionUser } from "@/lib/supabase/server";
import { AcceptInviteClient } from "@/components/members/AcceptInviteClient";

/**
 * Public-ish route: any authenticated user may land here; the tRPC
 * `members.acceptInvite` procedure enforces that the caller's email matches
 * the invite's email before joining the org.
 *
 * Unauthenticated callers are bounced to /login with a `redirectTo` query
 * param so Supabase magic-link / SSO flows bring them back to the token URL
 * after signup completes.
 */
export default async function AcceptInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const user = await getSessionUser();
  if (!user) {
    const redirectTo = encodeURIComponent(`/invite/${token}`);
    redirect(`/login?redirectTo=${redirectTo}`);
  }

  return (
    <main className="min-h-screen bg-paper text-ink flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-lg border border-lattice bg-paper-fold/60 p-7">
        <p className="font-sans text-[11px] uppercase tracking-[0.18em] text-graphite-soft">
          You've been invited
        </p>
        <h1 className="mt-2 font-display text-[28px] text-ink">
          Join the workspace
        </h1>
        <p className="mt-2 font-sans text-[14px] text-graphite">
          Accepting this invite will add you to the organization. You can
          leave later from settings.
        </p>
        <div className="mt-6">
          <AcceptInviteClient token={token} userEmail={user.email ?? ""} />
        </div>
      </div>
    </main>
  );
}
