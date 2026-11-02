import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

/**
 * Server Supabase client: for RSC, Route Handlers, and Server Actions.
 *
 * In RSC the cookie store is read-only; calls to `set`/`remove` are no-ops
 * wrapped in try/catch. Route Handlers / Server Actions CAN mutate cookies
 * (the Next.js runtime allows it in those contexts), so the same client
 * works everywhere.
 */
export async function createSupabaseServerClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      "Missing Supabase env: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY"
    );
  }

  const cookieStore = await cookies();

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(
        cookiesToSet: Array<{
          name: string;
          value: string;
          options: CookieOptions;
        }>
      ) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // RSC: cookies are read-only here. Safe to ignore; the
          // middleware refresh path handles session renewal.
        }
      },
    },
  });
}

/**
 * Convenience: resolve the current authenticated user (or null).
 * Use in RSC pages to guard content.
 */
export async function getSessionUser() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}
