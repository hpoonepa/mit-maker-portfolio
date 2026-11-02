import { NextResponse, type NextRequest } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { createServerTrpc } from "@/lib/trpc/server";
import { betaGateEnabled } from "@papercrane/types";

function betaAccessError(origin: string, message: string) {
  const signupUrl = new URL("/signup", origin);
  signupUrl.searchParams.set("error", message);
  return NextResponse.redirect(signupUrl);
}

/**
 * OAuth / magic-link callback handler.
 *
 * Supabase sends the user here with a `?code=...` param (PKCE flow) or with
 * `?error=...` on failure. We exchange the code for a session (which sets
 * cookies via our server client) and then redirect to the original target.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const errorDescription = searchParams.get("error_description");
  const redirectToParam = searchParams.get("redirectTo") ?? "/app";

  // Only allow same-origin relative redirect targets. Reject protocol-relative
  // (`//evil.com`), backslash-prefixed (`/\evil.com`), and anything that would
  // resolve off-origin. This is the canonical open-redirect guard for OAuth
  // callbacks: without it, an attacker can craft a magic-link URL that lands
  // the freshly-authed user on a phishing site after Supabase exchanges the
  // code for a session.
  const isSafeRelative =
    redirectToParam.startsWith("/") &&
    !redirectToParam.startsWith("//") &&
    !redirectToParam.startsWith("/\\");
  const safeRedirect = isSafeRelative ? redirectToParam : "/app";

  if (errorDescription) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("error", errorDescription);
    return NextResponse.redirect(loginUrl);
  }

  if (!code) {
    return NextResponse.redirect(new URL("/login", origin));
  }

  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("error", error.message);
    return NextResponse.redirect(loginUrl);
  }

  if (betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE)) {
    const metadataCode = data.user?.user_metadata?.beta_invite_code;
    const inviteCode =
      searchParams.get("invite") ??
      (typeof metadataCode === "string" ? metadataCode : undefined);

    try {
      const trpc = await createServerTrpc();
      const admission = await trpc.beta.claimInvite.mutate({
        ...(inviteCode ? { code: inviteCode } : {}),
      });
      if (!admission.ok) {
        await supabase.auth.signOut();
        const message =
          admission.reason === "expired"
            ? "That beta invite has expired. Ask for a new one."
            : admission.reason === "exhausted"
              ? "That beta invite has already been used."
              : "A valid beta invite is required for new accounts.";
        return betaAccessError(origin, message);
      }
    } catch {
      await supabase.auth.signOut();
      return betaAccessError(
        origin,
        "We couldn't verify beta access. Please try the sign-in link again.",
      );
    }
  }

  return NextResponse.redirect(new URL(safeRedirect, origin));
}
