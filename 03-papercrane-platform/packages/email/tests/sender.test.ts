import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sendMock = vi.hoisted(() => vi.fn());

vi.mock('resend', () => ({
  Resend: class {
    emails = { send: sendMock };
  },
}));

import { __resetIdempotencyCacheForTests, sendEmail } from '../src/sender';

const logger = {
  info: vi.fn(),
  warn: vi.fn(),
};

describe('sendEmail', () => {
  let tempDir: string;
  let logPath: string;

  beforeEach(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'papercrane-email-'));
    logPath = path.join(tempDir, 'sent.log');
    delete process.env.RESEND_API_KEY;
    __resetIdempotencyCacheForTests();
    sendMock.mockReset();
    logger.info.mockReset();
    logger.warn.mockReset();
  });

  afterEach(async () => {
    delete process.env.RESEND_API_KEY;
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it('renders a template and writes an observable dev record', async () => {
    const result = await sendEmail(
      {
        to: 'researcher@example.com',
        template: 'welcome',
        data: { userName: 'Ada', quickstartUrl: 'https://app.papercrane.bio/new' },
      },
      { devLogPath: logPath, logger },
    );

    expect(result).toMatchObject({ delivered: true, mode: 'dev-log', deduped: false });
    const record = JSON.parse((await fs.readFile(logPath, 'utf8')).trim()) as {
      to: string;
      htmlBytes: number;
      textBytes: number;
    };
    expect(record.to).toBe('researcher@example.com');
    expect(record.htmlBytes).toBeGreaterThan(100);
    expect(record.textBytes).toBeGreaterThan(20);
  });

  it('deduplicates repeated idempotency keys', async () => {
    const input = {
      to: 'researcher@example.com',
      template: 'welcome' as const,
      data: { quickstartUrl: 'https://app.papercrane.bio/new' },
      idempotencyKey: 'notification-1',
    };
    await sendEmail(input, { devLogPath: logPath, logger });
    const second = await sendEmail(input, { devLogPath: logPath, logger });

    expect(second.deduped).toBe(true);
    expect((await fs.readFile(logPath, 'utf8')).trim().split('\n')).toHaveLength(1);
  });

  it('rejects invalid recipient addresses before rendering', async () => {
    await expect(
      sendEmail(
        {
          to: 'not-an-email',
          template: 'welcome',
          data: { quickstartUrl: 'https://app.papercrane.bio/new' },
        },
        { devLogPath: logPath, logger },
      ),
    ).rejects.toThrow();
  });

  it('uses the real provider response in explicitly enabled live mode', async () => {
    process.env.RESEND_API_KEY = 're_test';
    sendMock.mockResolvedValue({ data: { id: 'email-123' }, error: null });

    const result = await sendEmail(
      {
        to: 'researcher@example.com',
        template: 'welcome',
        data: { quickstartUrl: 'https://app.papercrane.bio/new' },
      },
      { live: true, logger },
    );

    expect(result).toMatchObject({
      delivered: true,
      mode: 'resend',
      providerMessageId: 'email-123',
    });
    expect(sendMock).toHaveBeenCalledWith(
      expect.objectContaining({
        to: 'researcher@example.com',
        subject: expect.stringContaining('Welcome to Paper Crane'),
      }),
    );
  });

  it('does not claim delivery when Resend rejects the request', async () => {
    process.env.RESEND_API_KEY = 're_test';
    sendMock.mockResolvedValue({ data: null, error: { message: 'domain not verified' } });

    await expect(
      sendEmail(
        {
          to: 'researcher@example.com',
          template: 'welcome',
          data: { quickstartUrl: 'https://app.papercrane.bio/new' },
        },
        { live: true, logger },
      ),
    ).rejects.toThrow('domain not verified');
  });
});
