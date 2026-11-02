import { describe, expect, it, vi } from 'vitest';
import { errorEvent, progressEvent } from '@papercrane/jobs';
import {
  jobEventToLog,
  persistJobEvent,
  redactJobLogMessage,
} from '../src/jobLogs';

describe('job log persistence', () => {
  it('redacts credentials from provider error messages', () => {
    const input =
      'request failed Bearer abc.def token=modal-secret api_key:sk-live-secret https://user:pass@example.com';
    const output = redactJobLogMessage(input);

    expect(output).not.toContain('abc.def');
    expect(output).not.toContain('modal-secret');
    expect(output).not.toContain('sk-live-secret');
    expect(output).not.toContain('user:pass');
    expect(output).toContain('[REDACTED]');
  });

  it('stores structured progress without provider metric payloads', () => {
    expect(jobEventToLog(progressEvent(2, 5))).toEqual({
      level: 'info',
      event: 'progress',
      message: 'Progress: 2/5 designs',
      metadata: { completed: 2, total: 5 },
    });
  });

  it('persists a redacted error row', async () => {
    const create = vi.fn().mockResolvedValue({});
    await persistJobEvent(
      { jobLog: { create } } as never,
      { error: vi.fn() } as never,
      'job-1',
      errorEvent(false, 'token=top-secret'),
    );

    expect(create).toHaveBeenCalledWith({
      data: expect.objectContaining({
        jobId: 'job-1',
        level: 'error',
        message: 'token=[REDACTED]',
      }),
    });
  });
});
