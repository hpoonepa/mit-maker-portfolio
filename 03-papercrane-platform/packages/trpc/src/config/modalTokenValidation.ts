import { spawn } from 'node:child_process';

export const MODAL_TOKEN_VALIDATION_TIMEOUT_MS = 5_000;

export type ModalTokenValidationResult =
  | { ok: true }
  | { ok: false; reason: 'rejected' | 'unavailable' };

type ModalTokenInfoResult = {
  exitCode: number | null;
  stderr: string;
  timedOut: boolean;
};

export type RunModalTokenInfo = (input: {
  tokenId: string;
  tokenSecret: string;
  environment?: string;
  timeoutMs: number;
}) => Promise<ModalTokenInfoResult>;

/**
 * Validate credentials through the same supported Modal CLI auth path used by
 * the worker. The previous REST probe treated Modal's HTTP 200 gRPC error page
 * as success, so even invalid tokens appeared connected.
 */
export async function validateModalToken(
  tokenId: string,
  tokenSecret: string,
  environment?: string,
  runTokenInfo: RunModalTokenInfo = runModalTokenInfo,
): Promise<ModalTokenValidationResult> {
  const result = await runTokenInfo({
    tokenId,
    tokenSecret,
    environment,
    timeoutMs: MODAL_TOKEN_VALIDATION_TIMEOUT_MS,
  });

  if (result.exitCode === 0 && !result.timedOut) return { ok: true };
  if (result.timedOut) return { ok: false, reason: 'unavailable' };

  const message = result.stderr.toLowerCase();
  const rejected = [
    'token not found',
    'token id is malformed',
    'token secret is malformed',
    'invalid token',
    'unauthenticated',
    'authentication failed',
    'permission denied',
  ].some((text) => message.includes(text));

  return { ok: false, reason: rejected ? 'rejected' : 'unavailable' };
}

async function runModalTokenInfo(input: {
  tokenId: string;
  tokenSecret: string;
  environment?: string;
  timeoutMs: number;
}): Promise<ModalTokenInfoResult> {
  return new Promise((resolve) => {
    let stderr = '';
    let settled = false;
    let timedOut = false;

    const finish = (exitCode: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ exitCode, stderr, timedOut });
    };

    const child = spawn('modal', ['token', 'info'], {
      env: {
        ...process.env,
        MODAL_TOKEN_ID: input.tokenId,
        MODAL_TOKEN_SECRET: input.tokenSecret,
        ...(input.environment
          ? { MODAL_ENVIRONMENT: input.environment }
          : {}),
      },
      stdio: ['ignore', 'ignore', 'pipe'],
    });

    child.stderr?.setEncoding('utf8');
    child.stderr?.on('data', (chunk: string) => {
      stderr = (stderr + chunk).slice(-4_096);
    });

    child.on('error', () => finish(null));
    child.on('close', (code) => finish(code));

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
      finish(null);
    }, input.timeoutMs);
    timer.unref();
  });
}
