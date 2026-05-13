import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';

const testUserId = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

const OWN_EMAIL = 'own@example.com';
const OWN_USER_ID = 'own-user-profile-id';
const DELEGATED_EMAIL = 'delegated@example.com';
const DELEGATED_EMAIL_2 = 'delegated2@example.com';

function makeMessage(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    subject: `Subject ${id}`,
    from: { emailAddress: { address: `sender-${id}@example.com` } },
    receivedDateTime: '2024-01-01T00:00:00Z',
    parentFolderId: `folder-${id}`,
    webLink: `https://outlook.com/msg/${id}`,
    uniqueBody: { content: `Body ${id}` },
    bodyPreview: `Preview ${id}`,
    ...overrides,
  };
}

function createQuery(opts: {
  delegatedMailboxes?: string[];
  mockPost?: ReturnType<typeof vi.fn>;
  idTranslationMap?: Map<string, string>;
}) {
  const { delegatedMailboxes = [], mockPost, idTranslationMap = new Map() } = opts;

  const apiMock = { post: mockPost ?? vi.fn().mockResolvedValue({ responses: [] }) };
  const graphClientFactory = {
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    createClientForUser: vi.fn().mockReturnValue({ api: vi.fn().mockReturnValue(apiMock) } as any),
  };

  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({ id: OWN_USER_ID, email: OWN_EMAIL }),
  };

  const translateGraphIdsToImmutableIdsQuery = {
    run: vi.fn().mockResolvedValue(idTranslationMap),
  };

  const getMailboxesWithFullDelegatedAccessQuery = {
    run: vi.fn().mockResolvedValue(delegatedMailboxes),
  };

  const markAccountsNoFullAccessCommand = {
    run: vi.fn().mockResolvedValue(undefined),
  };

  const instance = new MsGraphKqlSearchEmailsQuery(
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    graphClientFactory as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    getUserProfileQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    translateGraphIdsToImmutableIdsQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    getMailboxesWithFullDelegatedAccessQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    markAccountsNoFullAccessCommand as any,
  );

  return {
    instance,
    apiMock,
    markAccountsNoFullAccessCommand,
    translateGraphIdsToImmutableIdsQuery,
    getMailboxesWithFullDelegatedAccessQuery,
  };
}

function makeSuccessPost(messagesByMailbox: Record<string, ReturnType<typeof makeMessage>[]>) {
  return vi.fn().mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
    const responses = requests.map((req) => {
      const mailbox = req.url.match(/\/users\/([^/]+)\/messages/)?.[1];
      const messages = (mailbox && messagesByMailbox[mailbox]) ?? [];
      return { id: req.id, status: 200, body: { value: messages } };
    });
    return Promise.resolve({ responses });
  });
}

describe('MsGraphKqlSearchEmailsQuery', () => {
  describe('fan-out', () => {
    it('creates one sub-request for own mailbox when no delegated access configured', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('msg1')] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }], 100);

      expect(mockPost).toHaveBeenCalledOnce();
      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/messages`);
      expect(results).toHaveLength(1);
    });

    it('fans out to own + all delegated mailboxes when no mailbox filter given', async () => {
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage('own-1')],
        [DELEGATED_EMAIL]: [makeMessage('del-1')],
        [DELEGATED_EMAIL_2]: [makeMessage('del-2')],
      });
      const { instance } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL, DELEGATED_EMAIL_2],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(3);
      const urls = requests.map((r: { url: string }) => r.url);
      expect(urls.some((u: string) => u.includes(OWN_EMAIL))).toBe(true);
      expect(urls.some((u: string) => u.includes(DELEGATED_EMAIL))).toBe(true);
      expect(urls.some((u: string) => u.includes(DELEGATED_EMAIL_2))).toBe(true);
      expect(results).toHaveLength(3);
    });

    it('caps delegated mailboxes at 25 when more are available', async () => {
      const thirtyDelegates = Array.from({ length: 30 }, (_, i) => `del${i}@example.com`);
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({ delegatedMailboxes: thirtyDelegates, mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      const totalRequests = mockPost.mock.calls.flatMap(
        (call) => (call[0] as { requests: unknown[] }).requests,
      );
      // own + 25 delegated = 26 (batch-chunked but total stays the same)
      expect(totalRequests).toHaveLength(26);
    });
  });

  describe('mailbox filter', () => {
    it('creates only one sub-request for own mailbox when mailbox = own email', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('own-1')] });
      const { instance } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: OWN_EMAIL },
      ], 100);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/messages`);
      expect(results[0]?.sourceMailbox).toBe(OWN_EMAIL);
    });

    it('creates only one sub-request for delegated mailbox when mailbox = delegated email', async () => {
      const mockPost = makeSuccessPost({ [DELEGATED_EMAIL]: [makeMessage('del-1')] });
      const { instance } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: DELEGATED_EMAIL },
      ], 100);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${DELEGATED_EMAIL}/messages`);
      expect(results[0]?.sourceMailbox).toBe(DELEGATED_EMAIL);
    });

    it('returns empty results with searchSummary when mailbox not in accessible set', async () => {
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL] });

      const { results, searchSummary } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: 'unknown@example.com' },
      ], 100);

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeDefined();
    });
  });

  describe('403/404 self-healing', () => {
    it('marks delegated accounts as no-full-access on 403 and excludes those results', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => {
            const isDelegated = req.url.includes(DELEGATED_EMAIL);
            return {
              id: req.id,
              status: isDelegated ? 403 : 200,
              body: isDelegated ? {} : { value: [makeMessage('own-1')] },
            };
          });
          return Promise.resolve({ responses });
        });

      const { instance, markAccountsNoFullAccessCommand } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(markAccountsNoFullAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
      });
      expect(results).toHaveLength(1);
      expect(results[0]?.sourceMailbox).toBe(OWN_EMAIL);
    });

    it('marks delegated accounts as no-full-access on 404', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => ({
            id: req.id,
            status: req.url.includes(DELEGATED_EMAIL) ? 404 : 200,
            body: req.url.includes(DELEGATED_EMAIL) ? {} : { value: [] },
          }));
          return Promise.resolve({ responses });
        });

      const { instance, markAccountsNoFullAccessCommand } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(markAccountsNoFullAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
      });
    });

    it('does not mark accounts for own mailbox 403', async () => {
      const _mockPost = vi.fn().mockResolvedValue({
        responses: [{ id: 'req-0', status: 403, body: {} }],
      });

      // Use a single-request setup matching the requestId
      const actualMockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string }[] }) =>
          Promise.resolve({
            responses: [{ id: requests[0]?.id, status: 403, body: {} }],
          }),
        );

      const { instance, markAccountsNoFullAccessCommand } = createQuery({
        mockPost: actualMockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(markAccountsNoFullAccessCommand.run).not.toHaveBeenCalled();
      expect(results).toHaveLength(0);
    });
  });

  describe('batch failure', () => {
    it('returns searchSummary error when graph batch throws', async () => {
      const mockPost = vi.fn().mockRejectedValue(new Error('network error'));
      const { instance } = createQuery({ mockPost });

      const { results, searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeDefined();
      expect(searchSummary).toMatch(/unavailable/i);
    });
  });

  describe('result merging', () => {
    it('interleaves results round-robin across mailboxes', async () => {
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage('own-1'), makeMessage('own-2'), makeMessage('own-3')],
        [DELEGATED_EMAIL]: [makeMessage('del-1'), makeMessage('del-2')],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results).toHaveLength(5);
      // Round-robin: own-1, del-1, own-2, del-2, own-3
      expect(results[0]?.msGraphMessageId).toBe('own-1');
      expect(results[1]?.msGraphMessageId).toBe('del-1');
      expect(results[2]?.msGraphMessageId).toBe('own-2');
      expect(results[3]?.msGraphMessageId).toBe('del-2');
      expect(results[4]?.msGraphMessageId).toBe('own-3');
    });

    it('caps results at 100 across all mailboxes', async () => {
      const manyMessages = Array.from({ length: 80 }, (_, i) => makeMessage(`own-${i}`));
      const manyMessages2 = Array.from({ length: 80 }, (_, i) => makeMessage(`del-${i}`));
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: manyMessages,
        [DELEGATED_EMAIL]: manyMessages2,
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test', limit: 50 }], 100);

      expect(results).toHaveLength(100);
    });

    it('deduplicates messages with the same restId across mailboxes', async () => {
      const duplicateId = 'duplicate-msg';
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage(duplicateId)],
        [DELEGATED_EMAIL]: [makeMessage(duplicateId)],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results).toHaveLength(1);
    });
  });

  describe('ID translation', () => {
    it('uses immutable ID from translation map when available', async () => {
      const restId = 'rest-id-123';
      const immutableId = 'immutable-id-abc';
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage(restId)] });
      const { instance } = createQuery({
        mockPost,
        idTranslationMap: new Map([[restId, immutableId]]),
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results[0]?.msGraphMessageId).toBe(immutableId);
    });

    it('falls back to restId when translation map has no entry for the message', async () => {
      const restId = 'rest-id-no-translation';
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage(restId)] });
      const { instance } = createQuery({ mockPost, idTranslationMap: new Map() });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results[0]?.msGraphMessageId).toBe(restId);
    });
  });

  describe('outlookWebLink', () => {
    it('includes webLink for own-mailbox results', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('own-1')] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results[0]?.outlookWebLink).toBe('https://outlook.com/msg/own-1');
    });

    it('sets outlookWebLink to empty string for delegated-mailbox results', async () => {
      const mockPost = makeSuccessPost({ [DELEGATED_EMAIL]: [makeMessage('del-1')] });
      const { instance } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: DELEGATED_EMAIL },
      ], 100);

      expect(results[0]?.outlookWebLink).toBe('');
    });
  });

  describe('non-2xx response handling', () => {
    it('skips sub-responses with non-2xx status without error', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => ({
            id: req.id,
            status: req.url.includes(OWN_EMAIL) ? 500 : 200,
            body: { value: [] },
          }));
          return Promise.resolve({ responses });
        });
      const { instance } = createQuery({ mockPost });

      const { results, searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeUndefined();
    });
  });

  describe('text content', () => {
    it('prefers uniqueBody content over bodyPreview', async () => {
      const msg = makeMessage('msg-1', {
        uniqueBody: { content: 'Full body content' },
        bodyPreview: 'Preview only',
      });
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [msg] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results[0]?.text).toBe('Full body content');
    });

    it('falls back to bodyPreview when uniqueBody is absent', async () => {
      const msg = makeMessage('msg-1', { uniqueBody: null, bodyPreview: 'Preview only' });
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [msg] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], 100);

      expect(results[0]?.text).toBe('Preview only');
    });
  });
});
