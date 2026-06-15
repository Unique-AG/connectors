/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphClientFactory } from '~/msgraph/graph-client.factory';
import type { ChatService } from './chat.service';
import { type SearchMessagesParams, SearchService } from './search.service';

const baseParams: SearchMessagesParams = {
  query: 'report',
  source: 'all',
  detail: 'summary',
  contentFormat: 'normalized',
  offset: 0,
  size: 25,
};

function makeHit(overrides: Record<string, any> = {}) {
  return {
    hitId: 'hit-1',
    rank: 1,
    summary: 'a summary snippet',
    resource: {
      id: 'msg-1',
      createdDateTime: '2024-01-15T10:00:00Z',
      webUrl: 'https://teams.microsoft.com/msg-1',
      from: { user: { id: 'u-1', displayName: 'Alice' } },
      chatId: '19:chat-1',
      ...overrides,
    },
  };
}

function makeResponse(hits: any[], moreResultsAvailable = false) {
  return {
    value: [{ hitsContainers: [{ hits, total: hits.length, moreResultsAvailable }] }],
  };
}

describe('SearchService', () => {
  let postMock: ReturnType<typeof vi.fn>;
  let versionMock: ReturnType<typeof vi.fn>;
  let apiMock: ReturnType<typeof vi.fn>;
  let graphClientFactory: GraphClientFactory;
  let chatService: ChatService;
  let service: SearchService;

  const traceService = { getSpan: () => undefined } as any;

  function mockSearchResponse(response: any) {
    postMock = vi.fn().mockResolvedValue(response);
    versionMock = vi.fn().mockReturnValue({ post: postMock });
    apiMock = vi.fn().mockReturnValue({ version: versionMock });
    graphClientFactory = {
      createClientForUser: vi.fn().mockReturnValue({ api: apiMock }),
    } as any;
  }

  beforeEach(() => {
    mockSearchResponse(makeResponse([makeHit()]));
    chatService = {
      getChatMessageById: vi.fn(),
      getChannelMessageById: vi.fn(),
    } as any;
    service = new SearchService(graphClientFactory, traceService, chatService);
  });

  it('posts the expected Microsoft Search request body', async () => {
    await service.searchMessages('user-1', { ...baseParams, offset: 10, size: 5 });

    expect(apiMock).toHaveBeenCalledWith('/search/query');
    expect(versionMock).toHaveBeenCalledWith('v1.0');
    expect(postMock).toHaveBeenCalledWith({
      requests: [
        {
          entityTypes: ['chatMessage'],
          query: { queryString: 'report' },
          from: 10,
          size: 5,
        },
      ],
    });
  });

  it('derives source=chat from chatId', async () => {
    const result = await service.searchMessages('user-1', baseParams);
    expect(result.messages[0]?.source).toBe('chat');
    expect(result.messages[0]?.chatId).toBe('19:chat-1');
    expect(result.messages[0]?.channelId).toBeNull();
  });

  it('derives source=channel from channelIdentity', async () => {
    mockSearchResponse(
      makeResponse([
        makeHit({
          chatId: undefined,
          channelIdentity: { teamId: 'team-1', channelId: 'channel-1' },
        }),
      ]),
    );
    service = new SearchService(graphClientFactory, traceService, chatService);

    const result = await service.searchMessages('user-1', baseParams);
    expect(result.messages[0]?.source).toBe('channel');
    expect(result.messages[0]?.teamId).toBe('team-1');
    expect(result.messages[0]?.channelId).toBe('channel-1');
  });

  it('flattens the sender display name, falling back to application', async () => {
    mockSearchResponse(
      makeResponse([
        makeHit({ from: { application: { displayName: 'Workflow Bot' }, user: undefined } }),
      ]),
    );
    service = new SearchService(graphClientFactory, traceService, chatService);

    const result = await service.searchMessages('user-1', baseParams);
    expect(result.messages[0]?.senderDisplayName).toBe('Workflow Bot');
  });

  it('applies the source filter after the fetch', async () => {
    mockSearchResponse(
      makeResponse([
        makeHit(),
        makeHit({
          id: 'msg-2',
          chatId: undefined,
          channelIdentity: { teamId: 'team-1', channelId: 'channel-1' },
        }),
      ]),
    );
    service = new SearchService(graphClientFactory, traceService, chatService);

    const result = await service.searchMessages('user-1', { ...baseParams, source: 'channel' });
    expect(result.messages).toHaveLength(1);
    expect(result.messages[0]?.source).toBe('channel');
    expect(result.returnedCount).toBe(1);
  });

  it('reads moreResultsAvailable from the first hits container', async () => {
    mockSearchResponse(makeResponse([makeHit()], true));
    service = new SearchService(graphClientFactory, traceService, chatService);

    const result = await service.searchMessages('user-1', baseParams);
    expect(result.moreResultsAvailable).toBe(true);
  });

  it('returns an empty result for an empty response', async () => {
    mockSearchResponse({ value: [] });
    service = new SearchService(graphClientFactory, traceService, chatService);

    const result = await service.searchMessages('user-1', baseParams);
    expect(result.messages).toEqual([]);
    expect(result.returnedCount).toBe(0);
    expect(result.moreResultsAvailable).toBe(false);
  });

  describe('detail=full hydration', () => {
    it('hydrates chat hits with the normalized message body', async () => {
      (chatService.getChatMessageById as any).mockResolvedValue({
        id: 'msg-1',
        createdDateTime: '2024-01-15T10:00:00Z',
        senderDisplayName: 'Alice',
        content: '<p>Hello <strong>world</strong></p>',
        contentType: 'html',
        attachments: [],
        messageType: 'message',
      });

      const result = await service.searchMessages('user-1', { ...baseParams, detail: 'full' });

      expect(chatService.getChatMessageById).toHaveBeenCalledWith('user-1', '19:chat-1', 'msg-1');
      expect(result.messages[0]?.content).toBe('Hello world');
    });

    it('hydrates channel hits via getChannelMessageById', async () => {
      mockSearchResponse(
        makeResponse([
          makeHit({
            id: 'msg-c',
            chatId: undefined,
            channelIdentity: { teamId: 'team-1', channelId: 'channel-1' },
          }),
        ]),
      );
      chatService = {
        getChatMessageById: vi.fn(),
        getChannelMessageById: vi.fn().mockResolvedValue({
          id: 'msg-c',
          createdDateTime: '2024-01-15T10:00:00Z',
          senderDisplayName: 'Alice',
          content: 'plain channel text',
          contentType: 'text',
          attachments: [],
          messageType: 'message',
        }),
      } as any;
      service = new SearchService(graphClientFactory, traceService, chatService);

      const result = await service.searchMessages('user-1', { ...baseParams, detail: 'full' });

      expect(chatService.getChannelMessageById).toHaveBeenCalledWith(
        'user-1',
        'team-1',
        'channel-1',
        'msg-c',
      );
      expect(result.messages[0]?.content).toBe('plain channel text');
    });

    it('falls back to the summary row when a hit fails to hydrate', async () => {
      (chatService.getChatMessageById as any).mockRejectedValue(new Error('403 Forbidden'));

      const result = await service.searchMessages('user-1', { ...baseParams, detail: 'full' });

      expect(result.messages).toHaveLength(1);
      expect(result.messages[0]?.content).toBeUndefined();
      expect(result.messages[0]?.summary).toBe('a summary snippet');
    });
  });
});
