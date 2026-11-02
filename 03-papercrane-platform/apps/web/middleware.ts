import { NextResponse, type NextRequest } from "next/server";

/**
 * Marketing site has no auth: middleware exists solely to attach
 * security headers (CSP, X-Frame-Options, etc.) to every response.
 *
 * Wave 15: beta hardening. Keep this loose enough that Next dev mode
 * (HMR + inline scripts) still works on localhost.
 */
const IS_DEV = process.env.NODE_ENV !== "production";
const CSP_DIRECTIVES: Record<string, string[]> = {
  "default-src": ["'self'"],
  // Next emits inline bootstrap scripts in prod ('unsafe-inline' stays).
  // 'unsafe-eval' is dev-only (HMR): production must not allow eval.
  "script-src": [
    "'self'",
    "'unsafe-inline'",
    ...(IS_DEV ? ["'unsafe-eval'"] : []),
    "https://js.stripe.com",
  ],
  "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
  "img-src": ["'self'", "data:", "blob:", "https://files.rcsb.org"],
  "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
  "connect-src": ["'self'", "https://*.supabase.co", "wss://*.supabase.co"],
  "frame-src": ["https://js.stripe.com"],
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

function withSecurityHeaders(response: NextResponse): NextResponse {
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

export function middleware(request: NextRequest) {
  const appUrl = (
    process.env.NODE_ENV === "production"
      ? "https://app.papercrane.bio"
      : process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3002"
  ).replace(/\/$/, "");
  const { pathname, search } = request.nextUrl;

  if (pathname === "/") {
    // Vercel's cleanUrls setting exposes public/_landing/index.html at
    // /_landing. Local Next servers still address the physical HTML file.
    const landingTarget = process.env.VERCEL
      ? "/_landing"
      : "/_landing/index.html";
    return withSecurityHeaders(
      NextResponse.rewrite(new URL(landingTarget, request.url)),
    );
  }

  if (pathname === "/app" || pathname.startsWith("/app/")) {
    return withSecurityHeaders(
      NextResponse.redirect(new URL(`${pathname}${search}`, appUrl)),
    );
  }

  const crossAppRoutes = new Set(["/login", "/logout", "/leaderboard"]);
  if (crossAppRoutes.has(pathname)) {
    return withSecurityHeaders(
      NextResponse.redirect(new URL(`${pathname}${search}`, appUrl)),
    );
  }

  return withSecurityHeaders(NextResponse.next());
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|otf)$).*)",
  ],
};
