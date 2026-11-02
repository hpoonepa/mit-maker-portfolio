/**
 * tRPC root — initializes `t` with our {@link Context}, SuperJSON transformer,
 * OpenAPI meta shape, and a Zod-aware error formatter. Procedures and routers
 * are built off the builders exported here.
 */
import { initTRPC, TRPCError } from '@trpc/server';
import superjson from 'superjson';
import type { OpenApiMeta } from 'trpc-to-openapi';
import { ZodError } from 'zod';
import type { Context } from './context.js';

export const t = initTRPC
  .context<Context>()
  .meta<OpenApiMeta>()
  .create({
    transformer: superjson,
    errorFormatter({ shape, error }) {
      return {
        ...shape,
        data: {
          ...shape.data,
          zod:
            error.cause instanceof ZodError ? error.cause.flatten() : null,
        },
      };
    },
  });

export const router = t.router;
export const publicProcedure = t.procedure;
export const middleware = t.middleware;

export { TRPCError };
