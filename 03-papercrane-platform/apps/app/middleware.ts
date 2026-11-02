import { NextResponse, type NextRequest } from "next/server";
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { getPublicApiBaseUrl } from "./lib/trpc/shared";

/**
 * Middleware responsibilities:
 *   1. Refresh the Supabase session cookie on every request so RSC pages
 *      see a valid `auth.getUser()`.
 *   2. Guard `/app/*`: redirect unauthenticated users to /login with a
 *      `redirectTo` query param so we can send them back after sign-in.
 *   3. Keep `/login` available so the landing-page entry always shows sign-in.
 *   4. Attach security headers (CSP, X-Frame-Options, HSTS in prod) to
 *      every response. Wave 15: beta hardening.
 */
const IS_DEV = process.env.NODE_ENV !== "production";
const CSP_DIRECTIVES: Record<string, string[]> = {
  "default-src": ["'self'"],
  // 'unsafe-eval' is dev-only (Next HMR). Production drops it.
  "script-src": [
    "'self'",
    "'unsafe-inline'",
    ...(IS_DEV ? ["'unsafe-eval'"] : []),
    "https://js.stripe.com",
  ],
  "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
  "img-src": [
    "'self'",
    "data:",
    "blob:",
    "https://files.rcsb.org",
    "https://www.rcsb.org",
    "https://*.rcsb.org",
    "https://www.ebi.ac.uk",
    "https://files.wwpdb.org",
  ],
  "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
  "connect-src": [
    "'self'",
    "data:",
    "blob:",
    "https://*.supabase.co",
    "wss://*.supabase.co",
    "https://files.rcsb.org",
    "https://www.rcsb.org",
    "https://*.rcsb.org",
    "https://www.ebi.ac.uk",
    "https://files.wwpdb.org",
    // Presigned design structures loaded by Molstar.
    "https://*.r2.cloudflarestorage.com",
    // BYOK Modal flow: user-supplied Modal endpoints (e.g. *.modal.run).
    "https://*.modal.run",
    "https://api.modal.com",
    new URL(getPublicApiBaseUrl()).origin,
  ],
  "frame-src": ["https://js.stripe.com"],
  "worker-src": ["'self'", "blob:"],
  "object-src": ["'none'"],
  "base-uri": ["'self'"],
  "form-action": ["'self'"],
  "frame-ancestors": ["'none'"],
};

function buildCsp(): string {
  return Object.entries(CSP_DIRECTIVES)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
}

function applySecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set("Content-Security-Policy", buildCsp());
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  if (process.env.NODE_ENV === "production") {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=63072000; includeSubDomains; preload",
    );
  }
  return response;
}
export async function middleware(request: NextRequest) {
  const response = NextResponse.next({
    request: { headers: request.headers },
  });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // If Supabase env is missing, short-circuit auth (e.g. local dev without .env)
  //: only redirect unauthenticated users on protected paths, and let public
  // pages render. This prevents a boot-time crash in the marketing app.
  if (!url || !anonKey) {
    if (request.nextUrl.pathname.startsWith("/app")) {
      const redirect = new URL("/login", request.url);
      redirect.searchParams.set("redirectTo", request.nextUrl.pathname);
      return applySecurityHeaders(NextResponse.redirect(redirect));
    }
    return applySecurityHeaders(response);
  }

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(
        cookiesToSet: Array<{
          name: string;
          value: string;
          options: CookieOptions;
        }>
      ) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set({ name, value, ...options });
        }
      },
    },
  });

  // IMPORTANT: getUser() (not getSession()): validates the JWT rather
  // than trusting a cookie value. This also triggers a refresh if needed.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const isAppRoute = pathname.startsWith("/app");

  if (isAppRoute && !user) {
    const redirect = new URL("/login", request.url);
    const redirectTo = pathname + request.nextUrl.search;
    redirect.searchParams.set("redirectTo", redirectTo);
    return applySecurityHeaders(NextResponse.redirect(redirect));
  }

  return applySecurityHeaders(response);
}

/**
 * Matcher: run on everything except static assets + image optimizer + the
 * Next-internal routes. Public auth pages still receive security headers.
 */
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|favicon.svg|og.png|robots.txt|sitemap.xml|\\.well-known/.*|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|otf|css|js)$).*)",
  ],
};
