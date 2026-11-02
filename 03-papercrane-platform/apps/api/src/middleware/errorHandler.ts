import type { FastifyError, FastifyReply, FastifyRequest } from "fastify";
import { ZodError } from "zod";
import { AuthError, ForbiddenError } from "@papercrane/auth";
import { captureException } from "@papercrane/observability";

/**
 * Shape returned on error responses. Intentionally small — enough for clients
 * to branch on without leaking stack traces or SQL text.
 */
export interface ErrorBody {
  error: string;
  message: string;
  /** Only present for validation errors; lists field-level issues. */
  issues?: Array<{ path: string; message: string }>;
}

/**
 * Global Fastify error handler.
 *
 * Mapping:
 *   - AuthError           → 401 (or 403 if ForbiddenError)
 *   - ZodError            → 400 (validation)
 *   - err.statusCode ≥ 400 → use it verbatim (Fastify builtins, 404s, etc.)
 *   - everything else     → 500 + Sentry capture
 *
 * We log with the request logger (pino) so every error is correlated with the
 * request id. Sentry captures 5xxs only — 4xxs are expected and not worth
 * noise.
 */
export function errorHandler(
  err: FastifyError,
  req: FastifyRequest,
  reply: FastifyReply,
): void {
  // 1) Zod validation errors
  if (err instanceof ZodError) {
    req.log.info({ issues: err.issues }, "validation failed");
    const body: ErrorBody = {
      error: "validation_error",
      message: "request failed validation",
      issues: err.issues.map((i) => ({
        path: i.path.join("."),
        message: i.message,
      })),
    };
    void reply.code(400).send(body);
    return;
  }

  // 2) Auth / forbidden — ForbiddenError extends AuthError so order matters.
  if (err instanceof ForbiddenError) {
    req.log.info(
      { code: err.code },
      "forbidden",
    );
    void reply.code(err.statusCode).send({
      error: err.code,
      message: err.message,
    });
    return;
  }
  if (err instanceof AuthError) {
    req.log.info({ code: err.code }, "unauthorized");
    void reply.code(err.statusCode).send({
      error: err.code,
      message: err.message,
    });
    return;
  }

  // 3) Anything with a known statusCode < 500 — treat as client error.
  const status = err.statusCode ?? 500;
  if (status < 500) {
    req.log.info({ err }, "client error");
    void reply.code(status).send({
      error: err.code ?? "bad_request",
      message: err.message,
    });
    return;
  }

  // 4) Server error — log stack, ship to Sentry, return generic message.
  req.log.error({ err }, "unhandled error");
  captureException(err, {
    url: req.url,
    method: req.method,
    requestId: req.id,
  });
  void reply.code(500).send({
    error: "internal_error",
    message: "an unexpected error occurred",
  });
}
