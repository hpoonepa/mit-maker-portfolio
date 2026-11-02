"use client";

import { TRPCReactProvider } from "@/lib/trpc/provider";
import { ToastProvider } from "@/components/toasts/ToastProvider";

/**
 * Top-level client providers for @papercrane/app. Any subtree that needs
 * tRPC + React Query should be wrapped in <Providers>.
 *
 * The `(dashboard)` layout already wraps its children in <Providers>, so
 * pages under `/app/*` inherit the tRPC client automatically. Public pages
 * inside this app (the leaderboard) do NOT mount this: they render as
 * pure RSC against the server-side tRPC caller.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <TRPCReactProvider>
      <ToastProvider>{children}</ToastProvider>
    </TRPCReactProvider>
  );
}
