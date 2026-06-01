import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GraphBatchRequest } from '../build-ms-graph-kql-batch-requests.query';
import { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';

const testUserId = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

const SEARCH_CONFIG = {
  maxEmailsLimit: 100,
  subQueryLimits: { min: 10, max: 150, default: 100, description: '' },
};

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

function makeRequest(
  overrides: Partial<GraphBatchRequest> & { mailbox: string; kqlQuery: string },
): GraphBatchRequest {
  return {
    requestId: `req-${Math.random().toString(36).slice(2)}`,
    isDelegated: false,
    limit: 100,
    ...overrides,
  };
}

function createQuery(opts: {
  delegatedMailboxes?: string[];
  mockPost?: ReturnType<typeof vi.fn>;
  idTranslationMap?: Map<string, string>;
  mockBuildResult?: {
    requests: GraphBatchRequest[];
    skippedFolders: Array<{ mailbox: string; folder: string }>;
  };
}) {
  const { delegatedMailboxes = [], mockPost, idTranslationMap = new Map(), mockBuildResult } = opts;

  // Build default mock result from delegatedMailboxes if mockBuildResult not explicitly provided
  const defaultBuildResult: {
    requests: GraphBatchRequest[];
    skippedFolders: Array<{ mailbox: string; folder: string }>;
  } = mockBuildResult ?? {
    requests: [
      makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false }),
      ...delegatedMailboxes.map((email) =>
        makeRequest({ mailbox: email, kqlQuery: 'test', isDelegated: true }),
      ),
    ],
    skippedFolders: [],
  };

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

  const buildMsGraphKqlBatchRequestsQuery = {
    run: vi.fn().mockResolvedValue(defaultBuildResult),
  };

  const removeDelegatedAccessCommand = {
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
    buildMsGraphKqlBatchRequestsQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    removeDelegatedAccessCommand as any,
  );

  return {
    instance,
    apiMock,
    removeDelegatedAccessCommand,
    translateGraphIdsToImmutableIdsQuery,
    buildMsGraphKqlBatchRequestsQuery,
  };
}

function makeSuccessPost(messagesByMailbox: Record<string, ReturnType<typeof makeMessage>[]>) {
  return vi.fn().mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
    const responses = requests.map((req) => {
      // Match both /users/{email}/messages and /users/{email}/mailFolders/{folderId}/messages
      const mailbox = req.url.match(/\/users\/([^/]+)\/(?:mailFolders\/[^/]+\/)?messages/)?.[1];
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

      const { results } = await instance.run(
        testUserId,
        [{ kqlQuery: 'subject:test' }],
        SEARCH_CONFIG,
      );

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(3);
      const urls = requests.map((r: { url: string }) => r.url);
      expect(urls.some((u: string) => u.includes(OWN_EMAIL))).toBe(true);
      expect(urls.some((u: string) => u.includes(DELEGATED_EMAIL))).toBe(true);
      expect(urls.some((u: string) => u.includes(DELEGATED_EMAIL_2))).toBe(true);
      expect(results).toHaveLength(3);
    });

    it('caps delegated mailboxes at 25 when more are available', async () => {
      // The capping happens inside BuildMsGraphKqlBatchRequestsQuery.
      // We simulate that by providing exactly 26 requests (own + 25 delegated).
      const twentyFiveDelegates = Array.from({ length: 25 }, (_, i) => `del${i}@example.com`);
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({ delegatedMailboxes: twentyFiveDelegates, mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

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
        mockBuildResult: {
          requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false })],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test', mailbox: OWN_EMAIL }],
        SEARCH_CONFIG,
      );

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/messages`);
      expect(results[0]?.sourceMailbox).toBe(OWN_EMAIL);
    });

    it('creates only one sub-request for delegated mailbox when mailbox = delegated email', async () => {
      const mockPost = makeSuccessPost({ [DELEGATED_EMAIL]: [makeMessage('del-1')] });
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [
            makeRequest({ mailbox: DELEGATED_EMAIL, kqlQuery: 'test', isDelegated: true }),
          ],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test', mailbox: DELEGATED_EMAIL }],
        SEARCH_CONFIG,
      );

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${DELEGATED_EMAIL}/messages`);
      expect(results[0]?.sourceMailbox).toBe(DELEGATED_EMAIL);
    });

    it('returns empty results with searchSummary when mailbox not in accessible set', async () => {
      const { instance } = createQuery({
        mockBuildResult: { requests: [], skippedFolders: [] },
      });

      const { results, searchSummary } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test', mailbox: 'unknown@example.com' }],
        SEARCH_CONFIG,
      );

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

      const { instance, removeDelegatedAccessCommand } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
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

      const { instance, removeDelegatedAccessCommand } = createQuery({
        delegatedMailboxes: [DELEGATED_EMAIL],
        mockPost,
      });

      await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
      });
    });

    it('does not mark accounts for own mailbox 403', async () => {
      const actualMockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string }[] }) =>
          Promise.resolve({
            responses: [{ id: requests[0]?.id, status: 403, body: {} }],
          }),
        );

      const { instance, removeDelegatedAccessCommand } = createQuery({
        mockPost: actualMockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(removeDelegatedAccessCommand.run).not.toHaveBeenCalled();
      expect(results).toHaveLength(0);
    });
  });

  describe('batch failure', () => {
    it('returns empty results when graph batch throws on both rounds', async () => {
      // Network errors are silently retried. If both rounds fail, results are empty
      // and no searchSummary is produced (there is nothing to report to the user
      // since the failure is transient and we have no partial results).
      const mockPost = vi.fn().mockRejectedValue(new Error('network error'));
      const { instance } = createQuery({ mockPost });

      const { results, searchSummary } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test' }],
        SEARCH_CONFIG,
      );

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeUndefined();
    });
  });

  describe('result merging', () => {
    it('interleaves results round-robin across mailboxes', async () => {
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage('own-1'), makeMessage('own-2'), makeMessage('own-3')],
        [DELEGATED_EMAIL]: [makeMessage('del-1'), makeMessage('del-2')],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results).toHaveLength(5);
      // Round-robin: own-1, del-1, own-2, del-2, own-3
      expect(results[0]?.msGraphMessageId).toBe('own-1');
      expect(results[1]?.msGraphMessageId).toBe('del-1');
      expect(results[2]?.msGraphMessageId).toBe('own-2');
      expect(results[3]?.msGraphMessageId).toBe('del-2');
      expect(results[4]?.msGraphMessageId).toBe('own-3');
    });

    it('caps results at searchConfig.maxEmailsLimit across all mailboxes', async () => {
      const manyMessages = Array.from({ length: 80 }, (_, i) => makeMessage(`own-${i}`));
      const manyMessages2 = Array.from({ length: 80 }, (_, i) => makeMessage(`del-${i}`));
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: manyMessages,
        [DELEGATED_EMAIL]: manyMessages2,
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results).toHaveLength(100);
    });

    it('deduplicates messages with the same restId across mailboxes', async () => {
      const duplicateId = 'duplicate-msg';
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage(duplicateId)],
        [DELEGATED_EMAIL]: [makeMessage(duplicateId)],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results[0]?.msGraphMessageId).toBe(immutableId);
    });

    it('falls back to restId when translation map has no entry for the message', async () => {
      const restId = 'rest-id-no-translation';
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage(restId)] });
      const { instance } = createQuery({ mockPost, idTranslationMap: new Map() });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results[0]?.msGraphMessageId).toBe(restId);
    });
  });

  describe('outlookWebLink', () => {
    it('includes webLink for own-mailbox results', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('own-1')] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results[0]?.outlookWebLink).toBe('https://outlook.com/msg/own-1');
    });

    it('sets outlookWebLink to empty string for delegated-mailbox results', async () => {
      const mockPost = makeSuccessPost({ [DELEGATED_EMAIL]: [makeMessage('del-1')] });
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [
            makeRequest({ mailbox: DELEGATED_EMAIL, kqlQuery: 'test', isDelegated: true }),
          ],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test', mailbox: DELEGATED_EMAIL }],
        SEARCH_CONFIG,
      );

      expect(results[0]?.outlookWebLink).toBe('');
    });
  });

  describe('non-2xx response handling', () => {
    it('skips sub-responses with 4xx status (not 403/404 delegated) without error', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => ({
            id: req.id,
            status: req.url.includes(OWN_EMAIL) ? 400 : 200,
            body: { value: [] },
          }));
          return Promise.resolve({ responses });
        });
      const { instance } = createQuery({ mockPost });

      const { results, searchSummary } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test' }],
        SEARCH_CONFIG,
      );

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results[0]?.text).toBe('Full body content');
    });

    it('falls back to bodyPreview when uniqueBody is absent', async () => {
      const msg = makeMessage('msg-1', { uniqueBody: null, bodyPreview: 'Preview only' });
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [msg] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results[0]?.text).toBe('Preview only');
    });
  });

  describe('folder-scoped requests', () => {
    // Case 3: directory-only delegated access — buildMsGraphKqlBatchRequestsQuery returns per-folder requests
    it('uses /mailFolders/{folderId}/messages URL when folderId is set', async () => {
      const folderId = 'folder-123';
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('msg-folder')] });
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [
            makeRequest({
              mailbox: OWN_EMAIL,
              kqlQuery: 'test',
              isDelegated: false,
              folderId,
            }),
          ],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/mailFolders/${folderId}/messages`);
      expect(results).toHaveLength(1);
    });

    it('uses /messages URL when no folderId is set', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('msg-no-folder')] });
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false })],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/messages`);
      expect(requests[0].url).not.toContain('mailFolders');
      expect(results).toHaveLength(1);
    });

    // Case 3: per-folder requests for the same mailbox — 403 on one folder does not drain the whole mailbox
    it('directory-only delegated: 403 on folder-level request does not trigger markNoAccess, sibling folder still returns results', async () => {
      const f1Id = 'folder-f1';
      const f2Id = 'folder-f2';

      const req1 = makeRequest({
        mailbox: DELEGATED_EMAIL,
        kqlQuery: 'test',
        isDelegated: true,
        folderId: f1Id,
      });
      const req2 = makeRequest({
        mailbox: DELEGATED_EMAIL,
        kqlQuery: 'test',
        isDelegated: true,
        folderId: f2Id,
      });

      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => {
            const isF1 = req.url.includes(f1Id);
            return {
              id: req.id,
              status: isF1 ? 403 : 200,
              body: isF1 ? {} : { value: [makeMessage('f2-msg')] },
            };
          });
          return Promise.resolve({ responses });
        });

      const { instance, removeDelegatedAccessCommand } = createQuery({
        mockBuildResult: {
          requests: [req1, req2],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { msGraphDirectoryId: f1Id },
      });
      expect(results.some((r) => r.msGraphMessageId === 'f2-msg')).toBe(true);
    });

    it('full-access delegated: 403 without folderId triggers markNoAccess and excludes all results for that mailbox', async () => {
      const req1 = makeRequest({
        mailbox: DELEGATED_EMAIL,
        kqlQuery: 'test',
        isDelegated: true,
      });
      const req2 = makeRequest({
        mailbox: OWN_EMAIL,
        kqlQuery: 'test',
        isDelegated: false,
      });

      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          const responses = requests.map((req) => {
            const isDelegated = req.url.includes(DELEGATED_EMAIL);
            return {
              id: req.id,
              status: isDelegated ? 403 : 200,
              body: isDelegated ? {} : { value: [makeMessage('own-msg')] },
            };
          });
          return Promise.resolve({ responses });
        });

      const { instance, removeDelegatedAccessCommand } = createQuery({
        mockBuildResult: {
          requests: [req1, req2],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledOnce();
      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
      });
      expect(results.every((r) => r.sourceMailbox === OWN_EMAIL)).toBe(true);
    });

    it('429 in round 1 → request retried in round 2 → results included and searchSummary mentions throttled', async () => {
      const delReq = makeRequest({
        mailbox: DELEGATED_EMAIL,
        kqlQuery: 'test',
        isDelegated: true,
      });

      let callCount = 0;
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) => {
          callCount++;
          const responses = requests.map((req) => ({
            id: req.id,
            status: callCount === 1 ? 429 : 200,
            body: callCount === 1 ? {} : { value: [makeMessage('throttled-msg')] },
          }));
          return Promise.resolve({ responses });
        });

      const { instance } = createQuery({
        mockBuildResult: {
          requests: [delReq],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results, searchSummary } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test' }],
        SEARCH_CONFIG,
      );

      expect(results.some((r) => r.msGraphMessageId === 'throttled-msg')).toBe(true);
      expect(searchSummary).toMatch(/throttled/i);
    });

    it('403 on full-access mailbox in first chunk drains that mailbox from subsequent chunks', async () => {
      // Case 6: "later chunks" queue drain — 25 DELEGATED_EMAIL requests + 1 OWN_EMAIL request.
      // First batch chunk (20 requests, all DELEGATED_EMAIL): first response is 403.
      // After 403, all remaining DELEGATED_EMAIL requests are drained from the queue.
      // Second batch chunk should contain only the OWN_EMAIL request.
      const delegatedRequests = Array.from({ length: 25 }, (_, i) =>
        makeRequest({
          mailbox: DELEGATED_EMAIL,
          isDelegated: true,
          kqlQuery: 'test',
          requestId: `del-${i}`,
        }),
      );
      const ownRequest = makeRequest({
        mailbox: OWN_EMAIL,
        isDelegated: false,
        kqlQuery: 'test',
        requestId: 'own-0',
      });

      const mockPost = vi
        .fn()
        .mockImplementationOnce(({ requests }: { requests: { id: string; url: string }[] }) => {
          // First batch of 20: all DELEGATED_EMAIL — first one gets 403
          return Promise.resolve({
            responses: requests.map((req, i) => ({
              id: req.id,
              status: i === 0 ? 403 : 200,
              body: i === 0 ? {} : { value: [] },
            })),
          });
        })
        .mockImplementationOnce(({ requests }: { requests: { id: string; url: string }[] }) => {
          // Second batch: expect only OWN_EMAIL request(s)
          return Promise.resolve({
            responses: requests.map((req) => ({
              id: req.id,
              status: 200,
              body: { value: [makeMessage('own-msg')] },
            })),
          });
        });

      const { instance, removeDelegatedAccessCommand } = createQuery({
        mockPost,
        mockBuildResult: { requests: [...delegatedRequests, ownRequest], skippedFolders: [] },
      });

      await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      // Second batch should only contain the own-mailbox request (DELEGATED_EMAIL was drained)
      const secondBatchRequests = mockPost.mock.calls[1]?.[0]?.requests as { url: string }[];
      expect(secondBatchRequests.every((r) => r.url.includes(OWN_EMAIL))).toBe(true);
      expect(secondBatchRequests.some((r) => r.url.includes(DELEGATED_EMAIL))).toBe(false);
      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledOnce();
    });

    it('searchSummary includes skipped folder name when build query returns skippedFolders', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('own-msg')] });
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false })],
          skippedFolders: [{ mailbox: 'a@b.com', folder: 'UnknownFolder' }],
        },
        mockPost,
      });

      const { searchSummary } = await instance.run(
        testUserId,
        [{ kqlQuery: 'test' }],
        SEARCH_CONFIG,
      );

      expect(searchSummary).toContain('UnknownFolder');
    });
  });

  describe('retry round', () => {
    it('network error in round 1 → whole batch retried in round 2 → round 2 succeeds', async () => {
      let callCount = 0;
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string }[] }) => {
          callCount++;
          if (callCount === 1) {
            return Promise.reject(new Error('network error'));
          }
          return Promise.resolve({
            responses: requests.map((req) => ({
              id: req.id,
              status: 200,
              body: { value: [makeMessage('retry-msg')] },
            })),
          });
        });

      const { instance } = createQuery({
        mockBuildResult: {
          requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false })],
          skippedFolders: [],
        },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }], SEARCH_CONFIG);

      expect(results.some((r) => r.msGraphMessageId === 'retry-msg')).toBe(true);
    });
  });
});
