/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AllDelegatesFailedError,
  MsGraphClientResolver,
  NoDelegatesFoundError,
} from './ms-graph-client-resolver.service';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const OWNER_USER_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef1';
const DELEGATE_USER_ID_1 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const DELEGATE_USER_ID_2 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';
const DELEGATE_USER_ID_3 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef4';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function makeGraphError(statusCode: number): GraphError {
  const err = new GraphError(statusCode, 'Graph error');
  err.statusCode = statusCode;
  return err;
}

function makeOauthProfile(id = OWNER_USER_ID) {
  return { id, email: 'owner@example.com', source: 'oauth' } as any;
}

function makeManualProfile(id = OWNER_USER_ID) {
  return { id, email: 'owner@example.com', source: 'shared-mailbox' } as any;
}

function createMockDb(delegates: { delegateUserId: string }[]) {
  const orderBy = vi.fn().mockResolvedValue(delegates);
  const where = vi.fn().mockReturnValue({ orderBy });
  const innerJoin = vi.fn().mockReturnValue({ where });
  const from = vi.fn().mockReturnValue({ innerJoin });
  const select = vi.fn().mockReturnValue({ from });

  return { select, __where: where };
}

function createMockGraphClientFactory() {
  return {
    createClientForUser: vi.fn().mockReturnValue({}),
  };
}

function createResolver(
  delegates: { delegateUserId: string }[],
  factory = createMockGraphClientFactory(),
) {
  const db = createMockDb(delegates);
  const resolver = new MsGraphClientResolver(db as any, factory as any);
  return { resolver, db, factory };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MsGraphClientResolver', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // OAuth path
  // -------------------------------------------------------------------------

  it('source=oauth: creates client for userProfile.id directly, calls fn, returns result without querying DB', async () => {
    const factory = createMockGraphClientFactory();
    const db = createMockDb([]);
    const resolver = new MsGraphClientResolver(db as any, factory as any);
    const fn = vi.fn().mockResolvedValue('oauth-result');
    const userProfile = makeOauthProfile();

    const result = await resolver.run({ userProfile, fn });

    expect(result).toBe('oauth-result');
    expect(factory.createClientForUser).toHaveBeenCalledOnce();
    expect(factory.createClientForUser).toHaveBeenCalledWith(OWNER_USER_ID);
    expect(fn).toHaveBeenCalledOnce();
    expect(fn).toHaveBeenCalledWith({ client: expect.any(Object), userProfile });
    expect(db.select).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Manual path
  // -------------------------------------------------------------------------

  it('source=manual, no delegates, sharedMailboxConfig omitted → returns null', async () => {
    const { resolver } = createResolver([]);

    const result = await resolver.run({
      userProfile: makeManualProfile(),
      fn: vi.fn(),
    });

    expect(result).toBeNull();
  });

  it('source=manual, no delegates, throwIfNoDelegates: true → throws NoDelegatesFoundError', async () => {
    const { resolver } = createResolver([]);

    await expect(
      resolver.run({
        userProfile: makeManualProfile(),
        fn: vi.fn(),
        sharedMailboxConfig: { throwIfNoDelegates: true },
      }),
    ).rejects.toThrow(NoDelegatesFoundError);
  });

  it('source=manual, first delegate succeeds → returns result, only one delegate tried', async () => {
    const fn = vi.fn().mockResolvedValue('success');
    const { resolver, db, factory } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
    ]);
    const userProfile = makeManualProfile();

    const result = await resolver.run({ userProfile, fn });

    expect(result).toBe('success');
    expect(db.__where).toHaveBeenCalledOnce();
    expect(factory.createClientForUser).toHaveBeenCalledOnce();
    expect(factory.createClientForUser).toHaveBeenCalledWith(DELEGATE_USER_ID_1);
    expect(fn).toHaveBeenCalledOnce();
    expect(fn).toHaveBeenCalledWith({ client: expect.any(Object), userProfile });
  });

  it('source=manual, first delegate throws 403, second succeeds → returns result from second', async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(makeGraphError(403))
      .mockResolvedValueOnce('from-second');

    const { resolver, factory } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
    ]);

    const result = await resolver.run({
      userProfile: makeManualProfile(),
      fn,
    });

    expect(result).toBe('from-second');
    expect(factory.createClientForUser).toHaveBeenCalledTimes(2);
    expect(factory.createClientForUser).toHaveBeenNthCalledWith(1, DELEGATE_USER_ID_1);
    expect(factory.createClientForUser).toHaveBeenNthCalledWith(2, DELEGATE_USER_ID_2);
  });

  it('source=manual, all delegates throw 403 → throws AllDelegatesFailedError', async () => {
    const fn = vi.fn().mockRejectedValue(makeGraphError(403));
    const { resolver } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
    ]);

    await expect(
      resolver.run({
        userProfile: makeManualProfile(),
        fn,
      }),
    ).rejects.toThrow(AllDelegatesFailedError);
  });

  it('source=manual, non-403 error → rethrows immediately, no more delegates tried', async () => {
    const nonFourOhThree = makeGraphError(500);
    const fn = vi
      .fn()
      .mockRejectedValueOnce(nonFourOhThree)
      .mockResolvedValueOnce('should-not-reach');

    const { resolver, factory } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
    ]);

    await expect(
      resolver.run({
        userProfile: makeManualProfile(),
        fn,
      }),
    ).rejects.toBe(nonFourOhThree);

    expect(factory.createClientForUser).toHaveBeenCalledOnce();
    expect(fn).toHaveBeenCalledOnce();
  });

  it('source=manual, maxRetries: 2 cap — with 3 delegates all throwing 403, only 2 tried', async () => {
    const fn = vi.fn().mockRejectedValue(makeGraphError(403));
    const { resolver, factory } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
      { delegateUserId: DELEGATE_USER_ID_3 },
    ]);

    await expect(
      resolver.run({
        userProfile: makeManualProfile(),
        fn,
        sharedMailboxConfig: { maxRetries: 2 },
      }),
    ).rejects.toThrow(AllDelegatesFailedError);

    expect(factory.createClientForUser).toHaveBeenCalledTimes(2);
    expect(factory.createClientForUser).not.toHaveBeenCalledWith(DELEGATE_USER_ID_3);
  });

  it('source=manual, default maxRetries=3 — with 4 delegates all throwing 403, only 3 tried', async () => {
    const fn = vi.fn().mockRejectedValue(makeGraphError(403));
    const { resolver, factory } = createResolver([
      { delegateUserId: DELEGATE_USER_ID_1 },
      { delegateUserId: DELEGATE_USER_ID_2 },
      { delegateUserId: DELEGATE_USER_ID_3 },
      { delegateUserId: 'user_profile_01jxk5r1s2fq9att23mp4z5ef5' },
    ]);

    await expect(
      resolver.run({
        userProfile: makeManualProfile(),
        fn,
      }),
    ).rejects.toThrow(AllDelegatesFailedError);

    expect(factory.createClientForUser).toHaveBeenCalledTimes(3);
  });
});
