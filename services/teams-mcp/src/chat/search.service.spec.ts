import { type Client } from '@microsoft/microsoft-graph-client';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { type MsChatMessage } from './chat.dtos';
import { ChatService } from './chat.service';
import { SearchService } from './search.service';

const userProfileId = 'user-profile-1';

const searchParams = {
  query: 'deploy',
  offset: 0,
  size: 25,
};

const chatHit = {
  hitId: 'hit-1',
  summary: 'Deploy is <c0>green</c0>.',
  resource: {
    id: 'msg-1',
    createdDateTime: '2024-06-20T13:50:00Z',
    webLink: 'https://outlook.office365.com/owa/?ItemID=abc',
    chatId: '19:chat-1@thread.v2',
    channelIdentity: {},
    from: { emailAddress: { name: 'Carol Lee', address: 'carol@contoso.com' } },
  },
};

const channelHit = {
  hitId: 'hit-2',
  summary: 'Release notes',
  resource: {
    id: 'msg-2',
    createdDateTime: '2024-06-20T14:00:00Z',
    channelIdentity: { teamId: 'team-1', channelId: '19:channel-1@thread.tacv2' },
    from: { user: { id: 'u-1', displayName: 'Dave Ops' } },
  },
};

const hydratedMessage: MsChatMessage = {
  id: 'msg-1',
  createdDateTime: '2024-06-20T13:50:01Z',
  senderDisplayName: 'Carol Lee (Teams)',
  content: '<p>Deploy is green.</p>',
  contentType: 'html',
  attachments: [],
  messageType: 'message',
  deletedDateTime: null,
};

const searchResponse = (hits: unknown[], moreResultsAvailable = false) => ({
  value: [{ hitsContainers: [{ hits, total: hits.length, moreResultsAvailable }] }],
});

async function buildHarness() {
  const post = vi.fn().mockResolvedValue(searchResponse([]));
  const graphClient = {
    api: vi.fn().mockReturnValue({ version: vi.fn().mockReturnValue({ post }) }),
  } as unknown as Client;

  const getChatMessageById = vi.fn().mockResolvedValue(hydratedMessage);
  const getChannelMessageById = vi.fn().mockResolvedValue(hydratedMessage);

  const { unit } = await TestBed.solitary(SearchService)
    .mock(GraphClientFactory)
    .impl(() => ({ createClientForUser: () => graphClient }))
    .mock(ChatService)
    .impl(() => ({ getChatMessageById, getChannelMessageById }))
    .compile();

  return { unit, post, getChatMessageById, getChannelMessageById };
}

type SearchHarness = Awaited<ReturnType<typeof buildHarness>>;

describe('SearchService', () => {
  let unit: SearchHarness['unit'];
  let post: SearchHarness['post'];
  let getChatMessageById: SearchHarness['getChatMessageById'];
  let getChannelMessageById: SearchHarness['getChannelMessageById'];

  beforeEach(async () => {
    ({ unit, post, getChatMessageById, getChannelMessageById } = await buildHarness());
  });

  describe('sender resolution', () => {
    it('reads the sender from the mailbox-shaped identity a search hit carries', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee');
    });

    it('reads the sender from the Teams user identity when Graph returns one', async () => {
      post.mockResolvedValue(searchResponse([channelHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Dave Ops');
    });

    it('reads the sender from an application identity', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: { ...chatHit.resource, from: { application: { displayName: 'Build Bot' } } },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Build Bot');
    });

    it('prefers the mailbox name over the Teams user identity when a hit carries both', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              from: {
                emailAddress: { name: 'Carol Lee', address: 'carol@contoso.com' },
                user: { id: 'u-2', displayName: 'Carol L. (Teams)' },
              },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee');
    });

    it('prefers the Teams user identity over an application identity', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              from: {
                user: { id: 'u-1', displayName: 'Dave Ops' },
                application: { displayName: 'Build Bot' },
              },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Dave Ops');
    });

    it('falls back to the mailbox address only once hydration names nobody either', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              from: { emailAddress: { address: 'carol@contoso.com' } },
            },
          },
        ]),
      );
      getChatMessageById.mockResolvedValue({ ...hydratedMessage, senderDisplayName: undefined });

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('carol@contoso.com');
    });

    it('prefers the hydrated display name over the mailbox address', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              from: { emailAddress: { address: 'carol@contoso.com' } },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee (Teams)');
    });

    it('treats an empty-string mailbox name as absent rather than as a name', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              from: { emailAddress: { name: '', address: 'carol@contoso.com' } },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee (Teams)');
    });

    it('reports no sender when neither the hit nor the hydrated message names anybody', async () => {
      post.mockResolvedValue(
        searchResponse([{ ...chatHit, resource: { ...chatHit.resource, from: {} } }]),
      );
      getChatMessageById.mockResolvedValue({ ...hydratedMessage, senderDisplayName: undefined });

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBeNull();
    });
  });

  describe('container classification', () => {
    it('classifies a hit carrying both channel ids as a channel and hydrates it there', async () => {
      post.mockResolvedValue(searchResponse([channelHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'channel',
        teamId: 'team-1',
        channelId: '19:channel-1@thread.tacv2',
      });
      expect(getChannelMessageById).toHaveBeenCalledWith(
        userProfileId,
        'team-1',
        '19:channel-1@thread.tacv2',
        'msg-2',
      );
      expect(getChatMessageById).not.toHaveBeenCalled();
    });

    it('classifies a hit carrying a channel id but no team id as a chat and hydrates it there', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              channelIdentity: { channelId: '19:channel-1@thread.tacv2' },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'chat',
        chatId: '19:chat-1@thread.v2',
        teamId: null,
        channelId: null,
      });
      expect(getChatMessageById).toHaveBeenCalledWith(
        userProfileId,
        '19:chat-1@thread.v2',
        'msg-1',
      );
      expect(getChannelMessageById).not.toHaveBeenCalled();
    });

    it('classifies a hit carrying a team id but no channel id as a chat and hydrates it there', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: { ...chatHit.resource, channelIdentity: { teamId: 'team-1' } },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'chat',
        chatId: '19:chat-1@thread.v2',
        teamId: null,
        channelId: null,
      });
      expect(getChatMessageById).toHaveBeenCalledWith(
        userProfileId,
        '19:chat-1@thread.v2',
        'msg-1',
      );
      expect(getChannelMessageById).not.toHaveBeenCalled();
    });

    it('classifies a hit carrying both channel ids and a chat id as a channel', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...channelHit,
            resource: { ...channelHit.resource, chatId: '19:chat-9@thread.v2' },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'channel',
        teamId: 'team-1',
        channelId: '19:channel-1@thread.tacv2',
        // A row never advertises a second container the caller could follow.
        chatId: null,
      });
      expect(getChannelMessageById).toHaveBeenCalled();
      expect(getChatMessageById).not.toHaveBeenCalled();
    });

    it('treats empty-string container ids as absent rather than as ids', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: {
              ...chatHit.resource,
              chatId: '',
              channelIdentity: { teamId: '', channelId: '' },
            },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'unknown',
        chatId: null,
        teamId: null,
        channelId: null,
      });
      expect(getChatMessageById).not.toHaveBeenCalled();
      expect(getChannelMessageById).not.toHaveBeenCalled();
    });

    it('classifies a hit carrying an empty channelIdentity as a chat', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.source).toBe('chat');
    });

    it('reports a hit carrying no container id as unknown and never calls Graph for it', async () => {
      post.mockResolvedValue(
        searchResponse([
          { ...chatHit, resource: { ...chatHit.resource, chatId: null, channelIdentity: {} } },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({
        source: 'unknown',
        chatId: null,
        teamId: null,
        channelId: null,
      });
      expect(result.messages[0]?.content).toBeUndefined();
      expect(getChatMessageById).not.toHaveBeenCalled();
      expect(getChannelMessageById).not.toHaveBeenCalled();
    });

    it('returns chat, channel and unknown hits from the same page', async () => {
      post.mockResolvedValue(
        searchResponse([
          chatHit,
          channelHit,
          { ...chatHit, resource: { ...chatHit.resource, chatId: null, channelIdentity: {} } },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages.map((m) => m.source)).toEqual(['chat', 'channel', 'unknown']);
      expect(result.returnedCount).toBe(3);
    });
  });

  describe('hydration', () => {
    it('normalizes the hydrated body into the content field', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.content).toBe('Deploy is green.');
    });

    it('keeps the hit sender when the hydrated message omits one', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));
      getChatMessageById.mockResolvedValue({
        ...hydratedMessage,
        senderDisplayName: undefined,
      });

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee');
    });

    it('keeps the hit sender in preference to the hydrated one, so a page reads consistently', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(getChatMessageById).toHaveBeenCalled();
      expect(hydratedMessage.senderDisplayName).not.toBe('Carol Lee');
      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee');
    });

    it('keeps the hit timestamp in preference to the hydrated one', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.createdDateTime).toBe('2024-06-20T13:50:00Z');
    });

    it('fills the timestamp from the hydrated message when the hit carries none', async () => {
      post.mockResolvedValue(
        searchResponse([{ ...chatHit, resource: { ...chatHit.resource, createdDateTime: null } }]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.createdDateTime).toBe('2024-06-20T13:50:01Z');
    });

    it('treats an empty-string hit timestamp as absent and fills it from the hydrated message', async () => {
      post.mockResolvedValue(
        searchResponse([{ ...chatHit, resource: { ...chatHit.resource, createdDateTime: '' } }]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.createdDateTime).toBe('2024-06-20T13:50:01Z');
    });

    it('never calls Graph for a hit that carries no message id', async () => {
      post.mockResolvedValue(
        searchResponse([{ ...chatHit, hitId: null, resource: { ...chatHit.resource, id: null } }]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]).toMatchObject({ id: '', source: 'chat' });
      expect(result.messages[0]?.content).toBeUndefined();
      expect(getChatMessageById).not.toHaveBeenCalled();
    });

    it('fills the sender from the hydrated message when the hit names nobody', async () => {
      post.mockResolvedValue(
        searchResponse([{ ...chatHit, resource: { ...chatHit.resource, from: {} } }]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.senderDisplayName).toBe('Carol Lee (Teams)');
    });

    it('returns a row without content when hydration throws', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));
      getChatMessageById.mockRejectedValue(new Error('Forbidden'));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.content).toBeUndefined();
      expect(result.messages[0]).toMatchObject({
        source: 'chat',
        senderDisplayName: 'Carol Lee',
        summary: 'Deploy is green.',
      });
    });

    // Graph retries a 429 three times honouring Retry-After, so a throttled hit
    // can hang for minutes. The page must still answer.
    it('returns a row without content when hydration outlives its budget', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));
      getChatMessageById.mockReturnValue(new Promise(() => {}));

      vi.useFakeTimers();
      try {
        const pending = unit.searchMessages(userProfileId, searchParams);
        await vi.advanceTimersByTimeAsync(20_000);
        const result = await pending;

        expect(result.messages[0]?.content).toBeUndefined();
        expect(result.messages[0]?.summary).toBe('Deploy is green.');
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('hit mapping', () => {
    it('strips hit-highlighting markup from the summary', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.summary).toBe('Deploy is green.');
    });

    it('falls back to the Exchange webLink when the hit carries no webUrl', async () => {
      post.mockResolvedValue(searchResponse([chatHit]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.webUrl).toBe('https://outlook.office365.com/owa/?ItemID=abc');
    });

    it('prefers the Teams webUrl over the Exchange webLink', async () => {
      post.mockResolvedValue(
        searchResponse([
          {
            ...chatHit,
            resource: { ...chatHit.resource, webUrl: 'https://teams.microsoft.com/l/message/1' },
          },
        ]),
      );

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.messages[0]?.webUrl).toBe('https://teams.microsoft.com/l/message/1');
    });

    it('surfaces the container pagination flag', async () => {
      post.mockResolvedValue(searchResponse([chatHit], true));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result.moreResultsAvailable).toBe(true);
    });

    it('asks Graph only for chat messages and pages by offset and size', async () => {
      await unit.searchMessages(userProfileId, { ...searchParams, offset: 25, size: 10 });

      expect(post).toHaveBeenCalledWith({
        requests: [
          {
            entityTypes: ['chatMessage'],
            query: { queryString: expect.any(String) },
            from: 25,
            size: 10,
          },
        ],
      });
    });

    it('logs the shape of an unaddressable hit and never its ids or content', async () => {
      post.mockResolvedValue(
        searchResponse([
          { ...chatHit, resource: { ...chatHit.resource, chatId: null, channelIdentity: {} } },
        ]),
      );

      await unit.searchMessages(userProfileId, searchParams);

      const debug = (Reflect.get(unit, 'logger') as { debug: Mock }).debug;
      const call = debug.mock.calls.find(
        ([, message]) =>
          message === 'Search hit is not addressable in Graph; returning it without content',
      );
      expect(call?.[0]).toEqual({
        userProfileId,
        source: 'unknown',
        hasMessageId: true,
        hasChatId: false,
        hasTeamId: false,
        hasChannelId: false,
      });
    });

    it('returns an empty page when Graph reports no hits', async () => {
      post.mockResolvedValue(searchResponse([]));

      const result = await unit.searchMessages(userProfileId, searchParams);

      expect(result).toEqual({ messages: [], returnedCount: 0, moreResultsAvailable: false });
    });
  });
});
