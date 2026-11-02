import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { Writable } from 'node:stream';
import { createLogger, createChildLogger } from '../src/logger.js';

function collectLogs(): { stream: Writable; lines: string[] } {
  const lines: string[] = [];
  const stream = new Writable({
    write(chunk, _enc, cb) {
      lines.push(chunk.toString());
      cb();
    },
  });
  return { stream, lines };
}

describe('createLogger', () => {
  const originalEnv = process.env.NODE_ENV;

  beforeEach(() => {
    process.env.NODE_ENV = 'production';
  });

  afterEach(() => {
    process.env.NODE_ENV = originalEnv;
  });

  it('returns a pino logger with expected shape', () => {
    const logger = createLogger({ service: 'test-svc' });
    expect(logger).toBeDefined();
    expect(typeof logger.info).toBe('function');
    expect(typeof logger.error).toBe('function');
    expect(typeof logger.warn).toBe('function');
    expect(typeof logger.debug).toBe('function');
    expect(typeof logger.child).toBe('function');
  });

  it('includes service in bindings', () => {
    const { stream, lines } = collectLogs();
    const logger = createLogger({ service: 'my-svc', stream });
    logger.info('hello');
    const entry = JSON.parse(lines[0]!);
    expect(entry.service).toBe('my-svc');
    expect(entry.msg).toBe('hello');
  });

  it('respects the level option', () => {
    const { stream, lines } = collectLogs();
    const logger = createLogger({ service: 'svc', level: 'warn', stream });
    logger.info('ignored');
    logger.warn('kept');
    expect(lines).toHaveLength(1);
    const entry = JSON.parse(lines[0]!);
    expect(entry.msg).toBe('kept');
  });

  it('redacts authorization header', () => {
    const { stream, lines } = collectLogs();
    const logger = createLogger({ service: 'svc', stream });
    logger.info({ req: { headers: { authorization: 'Bearer secret-token' } } }, 'request');
    const entry = JSON.parse(lines[0]!);
    expect(entry.req.headers.authorization).toBe('[Redacted]');
  });

  it('redacts api_key, apiKey, token, password, r2_secret_access_key', () => {
    const { stream, lines } = collectLogs();
    const logger = createLogger({ service: 'svc', stream });
    logger.info(
      {
        api_key: 'sk-123',
        apiKey: 'sk-456',
        token: 't-789',
        password: 'hunter2',
        r2_secret_access_key: 'r2-secret',
      },
      'payload',
    );
    const entry = JSON.parse(lines[0]!);
    expect(entry.api_key).toBe('[Redacted]');
    expect(entry.apiKey).toBe('[Redacted]');
    expect(entry.token).toBe('[Redacted]');
    expect(entry.password).toBe('[Redacted]');
    expect(entry.r2_secret_access_key).toBe('[Redacted]');
  });
});

describe('createChildLogger', () => {
  const originalEnv = process.env.NODE_ENV;

  beforeEach(() => {
    process.env.NODE_ENV = 'production';
  });

  afterEach(() => {
    process.env.NODE_ENV = originalEnv;
  });

  it('adds bindings to child logger output', () => {
    const { stream, lines } = collectLogs();
    const parent = createLogger({ service: 'svc', stream });
    const child = createChildLogger(parent, { requestId: 'req-123' });
    child.info('child-msg');
    const entry = JSON.parse(lines[0]!);
    expect(entry.requestId).toBe('req-123');
    expect(entry.service).toBe('svc');
    expect(entry.msg).toBe('child-msg');
  });
});
