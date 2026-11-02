"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { httpBatchLink } from "@trpc/client";
import { useState } from "react";
import superjson from "superjson";
import { createSupabaseBrowserClient } from "../supabase/client";
import { trpc } from "./client";
import { getTrpcUrl } from "./shared";
import { errorLoggerLink } from "./errorLoggerLink";

/**
 * Client-side tRPC + React Query provider. Wraps authenticated + public
 * client components so hooks like `trpc.projects.list.useQuery()` work.
 *
 * Attaches the current Supabase access token on every request via an
 * auth header so the API can identify the user.
 */
export function TRPCReactProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Treat data as fresh for 30s: matches typical job-status cadence
            staleTime: 30 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  const [trpcClient] = useState(() =>
    trpc.createClient({
      links: [
        // Dev-only: structured-log every error and POST to /api/dev/log-error.
        // No-op in production builds so the link is safe to keep in the chain.
        errorLoggerLink(),
        httpBatchLink({
          url: getTrpcUrl(),
          transformer: superjson,
          async headers() {
            const supabase = createSupabaseBrowserClient();
            const {
              data: { session },
            } = await supabase.auth.getSession();
            const headers: Record<string, string> = {
              "x-trpc-source": "browser",
            };
            if (session?.access_token) {
              headers.authorization = `Bearer ${session.access_token}`;
            }
            return headers;
          },
        }),
      ],
    })
  );

  return (
    <trpc.Provider client={trpcClient} queryClient={queryClient}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </trpc.Provider>
  );
}
