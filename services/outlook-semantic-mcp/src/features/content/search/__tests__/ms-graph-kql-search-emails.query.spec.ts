import { UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { describe, expect, it, type Mock, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GraphBatchRequest } from '../build-ms-graph-kql-batch-requests.query';
import { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';
import { SearchBackend, SearchPageStatus } from '../search-results.types';

vi.mock('~/utils/sleep', () => ({ sleep: vi.fn().mockResolvedValue(undefined) }));

const GRAPH_ROOT = 'https://graph.microsoft.com/v1.0';

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
    sentDateTime: '2024-01-01T00:00:00Z',
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
    limit: 25,
    ...overrides,
  };
}

function createQuery(opts: {
  delegatedMailboxes?: string[];
  mockPost?: Mock;
  idTranslationMap?: Map<string, string>;
  mockBuildResult?: {
    requests: GraphBatchRequest[];
    skippedFolders: Array<{ mailbox: string; folder: string }>;
    queriedMailboxesWithoutFullAccess?: string[];
  };
}) {
  const { delegatedMailboxes = [], mockPost, idTranslationMap = new Map(), mockBuildResult } = opts;

  // Build default mock result from delegatedMailboxes if mockBuildResult not explicitly provided
  const defaultBuildResult: {
    requests: GraphBatchRequest[];
    skippedFolders: Array<{ mailbox: string; folder: string }>;
    queriedMailboxesWithoutFullAccess: string[];
  } = {
    queriedMailboxesWithoutFullAccess: [],
    ...(mockBuildResult ?? {
      requests: [
        makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', isDelegated: false }),
        ...delegatedMailboxes.map((email) =>
          makeRequest({ mailbox: email, kqlQuery: 'test', isDelegated: true }),
        ),
      ],
      skippedFolders: [],
    }),
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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: OWN_EMAIL },
      ]);

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

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: DELEGATED_EMAIL },
      ]);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${DELEGATED_EMAIL}/messages`);
      expect(results[0]?.sourceMailbox).toBe(DELEGATED_EMAIL);
    });

    it('returns empty results with searchSummary when mailbox not in accessible set', async () => {
      const { instance } = createQuery({
        mockBuildResult: { requests: [], skippedFolders: [] },
      });

      const { results, searchSummary } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: 'unknown@example.com' },
      ]);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { results, searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeUndefined();
    });

    it('propagates a revoked Microsoft grant instead of reporting an empty mailbox', async () => {
      const revoked = new UpstreamCredentialRevokedError('invalid_grant');
      const mockPost = vi.fn().mockRejectedValue(revoked);
      const { instance } = createQuery({ mockPost });

      await expect(instance.run(testUserId, [{ kqlQuery: 'test' }])).rejects.toBe(revoked);
      expect(mockPost).toHaveBeenCalledTimes(1);
    });
  });

  describe('result merging', () => {
    it('merges results of all mailboxes newest first', async () => {
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [
          makeMessage('own-1', { receivedDateTime: '2024-01-05T00:00:00Z' }),
          makeMessage('own-2', { receivedDateTime: '2024-01-01T00:00:00Z' }),
        ],
        [DELEGATED_EMAIL]: [makeMessage('del-1', { receivedDateTime: '2024-01-03T00:00:00Z' })],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results.map((r) => r.msGraphMessageId)).toEqual(['own-1', 'del-1', 'own-2']);
    });

    it('returns every hit of every request without a count cap', async () => {
      const manyMessages = Array.from({ length: 80 }, (_, i) => makeMessage(`own-${i}`));
      const manyMessages2 = Array.from({ length: 80 }, (_, i) => makeMessage(`del-${i}`));
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: manyMessages,
        [DELEGATED_EMAIL]: manyMessages2,
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results).toHaveLength(160);
    });

    it('deduplicates messages with the same restId across mailboxes', async () => {
      const duplicateId = 'duplicate-msg';
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage(duplicateId)],
        [DELEGATED_EMAIL]: [makeMessage(duplicateId)],
      });
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results[0]?.msGraphMessageId).toBe(immutableId);
    });

    it('falls back to restId when translation map has no entry for the message', async () => {
      const restId = 'rest-id-no-translation';
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage(restId)] });
      const { instance } = createQuery({ mockPost, idTranslationMap: new Map() });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results[0]?.msGraphMessageId).toBe(restId);
    });
  });

  describe('replyToParams', () => {
    it('marks draft messages as not replyable', async () => {
      const mockPost = makeSuccessPost({
        [OWN_EMAIL]: [makeMessage('draft-1', { isDraft: true })],
      });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results[0]?.replyToParams).toEqual({
        inReplyToMessageId: 'draft-1',
        idIsImmutable: false,
        isReplyable: false,
      });
    });
  });

  describe('outlookWebLink', () => {
    it('includes webLink for own-mailbox results', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('own-1')] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results[0]?.outlookWebLink).toBe('https://outlook.com/msg/own-1');
    });

    it('includes webLink for delegated-mailbox results (Graph $search always returns classic OWA format)', async () => {
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

      const { results } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: DELEGATED_EMAIL },
      ]);

      expect(results[0]?.outlookWebLink).toBe('https://outlook.com/msg/del-1');
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

      const { results, searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results).toHaveLength(0);
      expect(searchSummary).toBeUndefined();
    });
  });

  describe('text content', () => {
    it('returns the body preview as text', async () => {
      const msg = makeMessage('msg-1', { bodyPreview: 'Preview only' });
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [msg] });
      const { instance } = createQuery({ mockPost });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results[0]?.text).toBe('Preview only');
    });

    it('never selects the message body from Graph', async () => {
      const mockPost = makeSuccessPost({ [OWN_EMAIL]: [makeMessage('msg-1')] });
      const { instance } = createQuery({ mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      const url = mockPost.mock.calls[0]?.[0]?.requests[0]?.url as string;
      const select = new URLSearchParams(url.split('?')[1]).get('$select')?.split(',');
      expect(select).toContain('bodyPreview');
      expect(select).not.toContain('body');
      expect(select).not.toContain('uniqueBody');
    });

    it('requests each page with the configured page size', async () => {
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({
        mockBuildResult: {
          requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', limit: 40 })],
          skippedFolders: [],
        },
        mockPost,
      });

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(mockPost.mock.calls[0]?.[0]?.requests[0]?.url).toContain('$top=40');
    });
  });

  describe('first-call result budget', () => {
    const fanOut = (count: number, limit: number) => ({
      requests: Array.from({ length: count }, (_, i) =>
        makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'test', folderId: `folder-${i}`, limit }),
      ),
      skippedFolders: [],
    });
    const requestedTops = (mockPost: Mock): string[] =>
      mockPost.mock.calls.flatMap((call) =>
        (call[0] as { requests: { url: string }[] }).requests.map(
          ({ url }) => new URLSearchParams(url.split('?')[1]).get('$top') ?? '',
        ),
      );

    it('shares the budget between the first pages of a wide fan-out', async () => {
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({ mockBuildResult: fanOut(10, 50), mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(requestedTops(mockPost)).toEqual(Array(10).fill('20'));
    });

    it('never shrinks a first page below the minimum page size', async () => {
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({ mockBuildResult: fanOut(60, 50), mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(requestedTops(mockPost)).toEqual(Array(60).fill('5'));
    });

    it('keeps the requested limit when the fan-out fits the budget', async () => {
      const mockPost = makeSuccessPost({});
      const { instance } = createQuery({ mockBuildResult: fanOut(3, 50), mockPost });

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(requestedTops(mockPost)).toEqual(['50', '50', '50']);
    });

    it('stores the nextLink of a shrunk first page exactly as Graph returned it', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) =>
          Promise.resolve({
            responses: requests.map((req) => ({
              id: req.id,
              status: 200,
              body: {
                value: [makeMessage(`msg-${req.id}`)],
                '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?%24search=%22test%22&%24top=20&%24skiptoken=abc`,
              },
            })),
          }),
        );
      const { instance } = createQuery({ mockBuildResult: fanOut(10, 50), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(pages[0]?.continuation).toMatchObject({
        url: `/users/${OWN_EMAIL}/messages?%24search=%22test%22&%24top=20&%24skiptoken=abc`,
        delivered: 1,
      });
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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      const requests = mockPost.mock.calls?.[0]?.[0]?.requests;
      expect(requests).toHaveLength(1);
      expect(requests[0].url).toContain(`/users/${OWN_EMAIL}/messages`);
      expect(requests[0].url).not.toContain('mailFolders');
      expect(results).toHaveLength(1);
    });

    it('403 on folder-scoped request triggers full-access removal and excludes all results from that mailbox', async () => {
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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
      });
      // f2-msg is from the same mailbox that got 403, so it is excluded via lostAccessMailboxes filter
      expect(results.some((r) => r.msGraphMessageId === 'f2-msg')).toBe(false);
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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledOnce();
      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
      });
      expect(results.every((r) => r.sourceMailbox === OWN_EMAIL)).toBe(true);
    });

    it('429 in round 1 → request retried in round 2 → results included and no searchSummary', async () => {
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

      const { results, searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results.some((r) => r.msGraphMessageId === 'throttled-msg')).toBe(true);
      expect(searchSummary).toBeUndefined();
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

      await instance.run(testUserId, [{ kqlQuery: 'test' }]);

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

      const { searchSummary } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(searchSummary).toContain('UnknownFolder');
    });
  });

  describe('queue drain across batches', () => {
    it('folder-level 403: drains all remaining requests for that entire mailbox, including sibling folders', async () => {
      // 21 requests for f1Id fill the first batch (20) and leave 1 in the queue.
      // When the first f1Id request gets 403, ALL remaining DELEGATED_EMAIL requests
      // (both leftover f1Id and the sibling f2Id) are drained from the queue.
      const f1Id = 'folder-f1';
      const f2Id = 'folder-f2';

      const f1Requests = Array.from({ length: 21 }, (_, i) =>
        makeRequest({
          mailbox: DELEGATED_EMAIL,
          kqlQuery: 'test',
          isDelegated: true,
          folderId: f1Id,
          requestId: `f1-${i}`,
        }),
      );
      const f2Request = makeRequest({
        mailbox: DELEGATED_EMAIL,
        kqlQuery: 'test',
        isDelegated: true,
        folderId: f2Id,
        requestId: 'f2-0',
      });

      const mockPost = vi
        .fn()
        .mockImplementationOnce(({ requests }: { requests: { id: string; url: string }[] }) => {
          // First batch of 20: all f1Id — first one 403, rest 200 (already out of queue)
          return Promise.resolve({
            responses: requests.map((req, i) => ({
              id: req.id,
              status: i === 0 ? 403 : 200,
              body: i === 0 ? {} : { value: [] },
            })),
          });
        });

      const { instance, removeDelegatedAccessCommand } = createQuery({
        mockBuildResult: { requests: [...f1Requests, f2Request], skippedFolders: [] },
        mockPost,
      });

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      // Both the leftover f1Id and the f2Id were drained from the queue — only one batch call
      expect(mockPost).toHaveBeenCalledOnce();
      expect(results.some((r) => r.msGraphMessageId === 'f2-msg')).toBe(false);
      expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
        delegateUserId: OWN_USER_ID,
        ownerEmail: DELEGATED_EMAIL,
        where: { fullAccess: true },
      });
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

      const { results } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results.some((r) => r.msGraphMessageId === 'retry-msg')).toBe(true);
    });
  });

  describe('pagination', () => {
    const singleRequest = (overrides: Partial<GraphBatchRequest> = {}) => ({
      requests: [makeRequest({ mailbox: OWN_EMAIL, kqlQuery: 'subject:test', ...overrides })],
      skippedFolders: [],
    });

    const respondWith = (subResponse: {
      status: number;
      headers?: Record<string, string>;
      body?: unknown;
    }) =>
      vi.fn().mockImplementation(({ requests }: { requests: { id: string }[] }) =>
        Promise.resolve({
          responses: requests.map((req) => ({ id: req.id, body: {}, ...subResponse })),
        }),
      );

    it('returns a hasMore page with the nextLink made relative when Graph has more results', async () => {
      const nextLink = `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$search=%22test%22&$top=25&$skip=25`;
      const mockPost = respondWith({
        status: 200,
        body: { value: [makeMessage('msg-1')], '@odata.nextLink': nextLink },
      });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages).toEqual([
        {
          backend: SearchBackend.MsGraph,
          query: 'subject:test',
          mailbox: OWN_EMAIL,
          folder: undefined,
          status: SearchPageStatus.HasMore,
          continuation: {
            backend: SearchBackend.MsGraph,
            kqlQuery: 'subject:test',
            mailbox: OWN_EMAIL,
            isDelegated: false,
            folderId: undefined,
            folderName: undefined,
            url: `/users/${OWN_EMAIL}/messages?$search=%22test%22&$top=25&$skip=25`,
            delivered: 1,
            chainHead: { id: 'msg-1', sentDateTime: '2024-01-01T00:00:00Z' },
          },
        },
      ]);
    });

    it('keeps paging when a page is empty but Graph still returns a nextLink', async () => {
      const mockPost = respondWith({
        status: 200,
        body: {
          value: [],
          '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$skip=50`,
        },
      });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.status).toBe(SearchPageStatus.HasMore);
    });

    it('returns a complete page without continuation when Graph has no nextLink', async () => {
      const mockPost = respondWith({ status: 200, body: { value: [makeMessage('msg-1')] } });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.status).toBe(SearchPageStatus.Complete);
      expect(pages[0]?.continuation).toBeUndefined();
    });

    it('keeps the hits of a page whose nextLink cannot be followed and continues the other pages', async () => {
      const mockPost = vi
        .fn()
        .mockImplementation(({ requests }: { requests: { id: string; url: string }[] }) =>
          Promise.resolve({
            responses: requests.map((req) => {
              const isOwn = req.url.includes(OWN_EMAIL);
              return {
                id: req.id,
                status: 200,
                body: {
                  value: [makeMessage(isOwn ? 'own-1' : 'del-1')],
                  '@odata.nextLink': isOwn
                    ? 'https://graph.microsoft.com/beta/users/own@example.com/messages?$skip=25'
                    : `${GRAPH_ROOT}/users/${DELEGATED_EMAIL}/messages?$skip=25`,
                },
              };
            }),
          }),
        );
      const { instance } = createQuery({ delegatedMailboxes: [DELEGATED_EMAIL], mockPost });

      const { results, pages } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(results.map((r) => r.msGraphMessageId).sort()).toEqual(['del-1', 'own-1']);
      const ownPage = pages.find((page) => page.mailbox === OWN_EMAIL);
      expect(ownPage?.status).toBe(SearchPageStatus.Failed);
      expect(ownPage?.continuation).toBeUndefined();
      expect(pages.find((page) => page.mailbox === DELEGATED_EMAIL)).toMatchObject({
        status: SearchPageStatus.HasMore,
        continuation: { url: `/users/${DELEGATED_EMAIL}/messages?$skip=25` },
      });
    });

    it('labels folder-scoped pages with the folder name', async () => {
      const mockPost = respondWith({ status: 200, body: { value: [] } });
      const { instance } = createQuery({
        mockBuildResult: singleRequest({ folderId: 'folder-1', folderName: 'Inbox' }),
        mockPost,
      });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.folder).toBe('Inbox');
    });

    it('reports a throttled first page with retryAfterSeconds and a continuation at the same position', async () => {
      const mockPost = respondWith({ status: 429, headers: { 'Retry-After': '7' } });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages, searchSummary } = await instance.run(testUserId, [
        { kqlQuery: 'subject:test' },
      ]);

      expect(mockPost).toHaveBeenCalledTimes(2);
      const firstPageUrl = mockPost.mock.calls[0]?.[0]?.requests[0]?.url;
      expect(pages[0]).toMatchObject({
        status: SearchPageStatus.Throttled,
        retryAfterSeconds: 7,
        continuation: { url: firstPageUrl, delivered: 0 },
        retryCursorId: undefined,
      });
      expect(searchSummary).toContain(OWN_EMAIL);
    });

    it('reports a failed page with a continuation when Graph keeps returning 5xx', async () => {
      const mockPost = respondWith({ status: 503 });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.status).toBe(SearchPageStatus.Failed);
      expect(pages[0]?.retryAfterSeconds).toBeUndefined();
      expect(pages[0]?.continuation).toBeDefined();
    });

    it('reports a rejected first page as failed without a continuation', async () => {
      const mockPost = respondWith({ status: 400 });
      const { instance } = createQuery({ mockBuildResult: singleRequest(), mockPost });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.status).toBe(SearchPageStatus.Failed);
      expect(pages[0]?.continuation).toBeUndefined();
    });

    it('reports revoked delegated access as accessRevoked', async () => {
      const mockPost = respondWith({ status: 403 });
      const { instance } = createQuery({
        mockBuildResult: singleRequest({ mailbox: DELEGATED_EMAIL, isDelegated: true }),
        mockPost,
      });

      const { pages } = await instance.run(testUserId, [{ kqlQuery: 'subject:test' }]);

      expect(pages[0]?.status).toBe(SearchPageStatus.AccessRevoked);
      expect(pages[0]?.continuation).toBeUndefined();
    });

    describe('fetchNextPages', () => {
      const CHAIN_HEAD = { id: 'msg-1', sentDateTime: '2024-03-01T00:00:00Z' };
      const olderMessage = (id: string) =>
        makeMessage(id, { sentDateTime: '2024-02-01T00:00:00Z' });
      const storedCursor = (overrides: Record<string, unknown> = {}, createdAt = new Date()) => ({
        id: 'search_cursor_1',
        createdAt,
        payload: {
          backend: SearchBackend.MsGraph as const,
          kqlQuery: 'subject:test',
          mailbox: OWN_EMAIL,
          isDelegated: false,
          url: `/users/${OWN_EMAIL}/messages?$skip=25`,
          delivered: 25,
          chainHead: CHAIN_HEAD,
          ...overrides,
        },
      });

      it('requests the stored url verbatim and counts delivered results across pages', async () => {
        const mockPost = respondWith({
          status: 200,
          body: {
            value: [olderMessage('msg-26')],
            '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$skip=50`,
          },
        });
        const { instance } = createQuery({ mockPost });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(mockPost.mock.calls[0]?.[0]?.requests[0]?.url).toBe(
          `/users/${OWN_EMAIL}/messages?$skip=25`,
        );
        expect(results.map((r) => r.msGraphMessageId)).toEqual(['msg-26']);
        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.HasMore,
          continuation: {
            url: `/users/${OWN_EMAIL}/messages?$skip=50`,
            delivered: 26,
            chainHead: CHAIN_HEAD,
          },
        });
      });

      it('keeps the same cursor id when the page is throttled again', async () => {
        const mockPost = respondWith({ status: 429 });
        const { instance } = createQuery({ mockPost });

        const { pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.Throttled,
          retryCursorId: 'search_cursor_1',
          continuation: {
            url: `/users/${OWN_EMAIL}/messages?$skip=25`,
            delivered: 25,
            chainHead: CHAIN_HEAD,
          },
        });
      });

      it('reports expired without results when Graph serves the first page again', async () => {
        const mockPost = respondWith({
          status: 200,
          body: {
            value: [makeMessage('msg-1', { sentDateTime: CHAIN_HEAD.sentDateTime })],
            '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$skip=50`,
          },
        });
        const { instance } = createQuery({ mockPost });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(results).toEqual([]);
        expect(pages[0]?.status).toBe(SearchPageStatus.Expired);
        expect(pages[0]?.continuation).toBeUndefined();
      });

      it('reports expired when the page holds an email sent after the chain head', async () => {
        const mockPost = respondWith({
          status: 200,
          body: {
            value: [
              makeMessage('newer', { sentDateTime: '2024-04-01T00:00:00Z' }),
              olderMessage('msg-26'),
            ],
          },
        });
        const { instance } = createQuery({ mockPost });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(results).toEqual([]);
        expect(pages[0]?.status).toBe(SearchPageStatus.Expired);
      });

      it('keeps results that share the chain head sent time but are other emails', async () => {
        const mockPost = respondWith({
          status: 200,
          body: { value: [makeMessage('msg-2', { sentDateTime: CHAIN_HEAD.sentDateTime })] },
        });
        const { instance } = createQuery({ mockPost });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(results.map((r) => r.msGraphMessageId)).toEqual(['msg-2']);
        expect(pages[0]?.status).toBe(SearchPageStatus.Complete);
      });

      it('takes the chain head from a retried first page', async () => {
        const mockPost = respondWith({
          status: 200,
          body: {
            value: [makeMessage('msg-1', { sentDateTime: CHAIN_HEAD.sentDateTime })],
            '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$skip=25`,
          },
        });
        const { instance } = createQuery({ mockPost });

        const { results, pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ url: `/users/${OWN_EMAIL}/messages`, delivered: 0, chainHead: undefined }),
        ]);

        expect(results.map((r) => r.msGraphMessageId)).toEqual(['msg-1']);
        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.HasMore,
          continuation: { delivered: 1, chainHead: CHAIN_HEAD },
        });
      });

      it('reports a stored url that Graph rejects as expired', async () => {
        const mockPost = respondWith({ status: 400 });
        const { instance } = createQuery({ mockPost });

        const { pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(pages[0]?.status).toBe(SearchPageStatus.Expired);
        expect(pages[0]?.continuation).toBeUndefined();
      });

      it('stops with ceilingReached once the chain has delivered the maximum results', async () => {
        const mockPost = respondWith({
          status: 200,
          body: {
            value: Array.from({ length: 10 }, (_, i) => olderMessage(`msg-${991 + i}`)),
            '@odata.nextLink': `${GRAPH_ROOT}/users/${OWN_EMAIL}/messages?$skip=1000`,
          },
        });
        const { instance } = createQuery({ mockPost });

        const { pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ delivered: 990 }),
        ]);

        expect(pages[0]?.status).toBe(SearchPageStatus.CeilingReached);
        expect(pages[0]?.continuation).toBeUndefined();
      });

      it('removes delegated access on a 404 for a recently stored cursor', async () => {
        const mockPost = respondWith({ status: 404 });
        const { instance, removeDelegatedAccessCommand } = createQuery({ mockPost });

        const { pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ mailbox: DELEGATED_EMAIL, isDelegated: true }),
        ]);

        expect(pages[0]?.status).toBe(SearchPageStatus.AccessRevoked);
        expect(removeDelegatedAccessCommand.run).toHaveBeenCalledWith({
          delegateUserId: OWN_USER_ID,
          ownerEmail: DELEGATED_EMAIL,
          where: { fullAccess: true },
        });
      });

      it('reports a 404 for a cursor older than 30 minutes as expired and keeps delegated access', async () => {
        const mockPost = respondWith({ status: 404 });
        const { instance, removeDelegatedAccessCommand } = createQuery({ mockPost });

        const { pages } = await instance.fetchNextPages(testUserId, [
          storedCursor(
            { mailbox: DELEGATED_EMAIL, isDelegated: true },
            new Date(Date.now() - 31 * 60 * 1000),
          ),
        ]);

        expect(pages[0]?.status).toBe(SearchPageStatus.Expired);
        expect(pages[0]?.continuation).toBeUndefined();
        expect(removeDelegatedAccessCommand.run).not.toHaveBeenCalled();
      });
    });
  });
});
