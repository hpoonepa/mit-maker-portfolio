import "server-only";

import { createTRPCProxyClient, httpBatchLink } from "@trpc/client";
import superjson from "superjson";
import { createSupabaseServerClient } from "../supabase/server";
import { getTrpcUrl, type AppRouter } from "./shared";

/**
 * Server-side tRPC caller for use in RSC pages and Server Actions.
 *
 * Forwards the current Supabase session's access token as a Bearer header
 * so the API can authenticate the user on behalf of this request.
 *
 * NOTE: We use an HTTP client against the remote Fastify API rather than a
 * direct server caller because the tRPC server lives in a separate process
 * (see plan 01 §8: api.papercrane.bio on Fly). Once the router is colocated
 * this can switch to `appRouter.createCaller(ctx)` for a zero-HTTP hop.
 */
export async function createServerTrpc() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  return createTRPCProxyClient<AppRouter>({
    links: [
      httpBatchLink({
        url: getTrpcUrl(),
        transformer: superjson,
        headers() {
          const headers: Record<string, string> = {
            "x-trpc-source": "rsc",
          };
          if (token) {
            headers.authorization = `Bearer ${token}`;
          }
          return headers;
        },
      }),
    ],
  });
}
