import { describe, expect, it, vi } from 'vitest';
import { feedbackRouter } from '../feedback.js';
import { createTestContext } from './_helpers.js';

function setup(joined = false) {
  const findMany = vi.fn(async () => joined ? [{ id: 'existing' }] : []);
  const create = vi.fn(async () => ({ id: 'new' }));
  const tx = { feedback: { findMany, create } };
  const context = createTestContext({
    auth: { kind: 'user', userId: 'u1', orgId: 'o1', orgSlug: 'lab', tier: 'free', scopes: ['*'] },
    prisma: tx as never,
    withRlsUser: (async (_db: unknown, _user: string, fn: (db: typeof tx) => Promise<unknown>) => fn(tx)) as never,
  });
  return { caller: feedbackRouter.createCaller(context), findMany, create };
}

describe('molecular dynamics waitlist', () => {
  it('requires authentication', async () => {
    const caller = feedbackRouter.createCaller(createTestContext({auth:null}));
    await expect(caller.joinMolecularDynamicsWaitlist()).rejects.toThrow(/unauthori[sz]ed/i);
    await expect(caller.molecularDynamicsWaitlist()).rejects.toThrow(/unauthori[sz]ed/i);
  });
  it('stores interest against the authenticated account', async () => {
    const {caller, create} = setup();
    await expect(caller.joinMolecularDynamicsWaitlist()).resolves.toEqual({joined:true});
    expect(create).toHaveBeenCalledWith({data: expect.objectContaining({userId:'u1',orgId:'o1',metadata:{waitlist:'molecular-dynamics'}})});
  });
  it('keeps status scoped to the current user and organization', async () => {
    const {caller, findMany} = setup(true);
    await expect(caller.molecularDynamicsWaitlist()).resolves.toEqual({joined:true});
    expect(findMany).toHaveBeenCalledWith({where:{userId:'u1',orgId:'o1',metadata:{path:['waitlist'],equals:'molecular-dynamics'}},take:1});
  });
  it('does not create another entry when already joined', async () => {
    const {caller, create} = setup(true);
    await caller.joinMolecularDynamicsWaitlist();
    expect(create).not.toHaveBeenCalled();
  });
  it('does not report success when persistence fails', async () => {
    const {caller, create} = setup();
    create.mockRejectedValueOnce(new Error('database unavailable'));
    await expect(caller.joinMolecularDynamicsWaitlist()).rejects.toThrow('database unavailable');
  });
});
