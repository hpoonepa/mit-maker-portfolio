/**
 * Shared test helpers for tRPC router tests.
 *
 * `createTestContext` wraps `createInnerContext` and adds the `req` shim that
 * the outer `Context` type now requires (Wave 12 router changes). Keeps test
 * files concise without modifying the production context module.
 */
import {
  createInnerContext,
  type Context,
  type CreateInnerContextOptions,
} from '../../context.js';

export function createTestContext(opts: CreateInnerContextOptions = {}): Context {
  const inner = createInnerContext(opts);
  return {
    ...inner,
    req: { headers: {} },
  };
}
