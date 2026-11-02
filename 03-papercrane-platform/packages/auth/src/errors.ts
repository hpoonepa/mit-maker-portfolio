/**
 * Auth errors. Throw these from verify/authorize paths; HTTP adapters
 * (Fastify plugins, tRPC middleware) translate them into responses.
 */

export class AuthError extends Error {
  public readonly statusCode: number = 401;
  public readonly code: string;

  constructor(message: string, code: string = 'unauthorized') {
    super(message);
    this.name = 'AuthError';
    this.code = code;
    // Restore prototype chain for instanceof to work when targeting older runtimes
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ForbiddenError extends AuthError {
  public override readonly statusCode: number = 403;

  constructor(message: string, code: string = 'forbidden') {
    super(message, code);
    this.name = 'ForbiddenError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
