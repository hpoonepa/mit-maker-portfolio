"use client";

import { createTRPCReact } from "@trpc/react-query";
import type { AppRouter } from "./shared";

/**
 * Typed tRPC React Query client. Use in Client Components:
 *
 *   const { data } = trpc.projects.list.useQuery();
 */
export const trpc = createTRPCReact<AppRouter>();
