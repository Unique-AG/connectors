import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { GetChannelMessagesInputSchema, GetChannelMessagesTool } from './get-channel-messages.tool';
import { GetChatMessagesInputSchema, GetChatMessagesTool } from './get-chat-messages.tool';

const request = { user: { userProfileId: 'user-profile-1' } } as McpAuthenticatedRequest;
const context = {} as Context;

const htmlMessage: MsChatMessage = {
  id: '1657782060227',
  createdDateTime: '2026-07-14T07:01:01.123Z',
  senderDisplayName: 'Carol Lee',
  content: '<p>Deploy is <strong>green</strong>.</p>',
  contentType: 'html',
  attachments: [],
  messageType: 'message',
  deletedDateTime: null,
};

describe.each([
  { name: 'get_chat_messages', schema: GetChatMessagesInputSchema, base: { chatId: 'chat-1' } },
  {
    name: 'get_channel_messages',
    schema: GetChannelMessagesInputSchema,
    base: { teamId: 'team-1', channelId: 'channel-1' },
  },
])('$name input schema', ({ schema, base }) => {
  it('keeps the Graph page defaults rather than the search page bound', () => {
    expect(schema.parse(base)).toMatchObject({ limit: 20, includeSystemMessages: false });
  });

  // These tools issue one Graph read per call and never fan out per message, so
  // the 25 that bounds search_messages does not apply. 50 is Graph's own maximum.
  it('accepts the Graph maximum of 50', () => {
    expect(schema.parse({ ...base, limit: 50 }).limit).toBe(50);
  });

  it('rejects a limit above the Graph maximum', () => {
    expect(schema.safeParse({ ...base, limit: 51 }).success).toBe(false);
  });

  it('drops the content-shaping parameters an older client still sends', () => {
    const parsed = schema.parse({
      ...base,
      contentFormat: 'raw',
      timestampFormat: 'none',
      detail: 'full',
    });

    expect(parsed).not.toHaveProperty('contentFormat');
    expect(parsed).not.toHaveProperty('timestampFormat');
    expect(parsed).not.toHaveProperty('detail');
  });
});

describe('GetChatMessagesTool', () => {
  let unit: GetChatMessagesTool;
  let getChatMessages: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    getChatMessages = vi.fn().mockResolvedValue([htmlMessage]);

    ({ unit } = await TestBed.solitary(GetChatMessagesTool)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => undefined }))
      .mock(ChatService)
      .impl(() => ({ getChatMessages }))
      .compile());
  });

  it('normalizes the body and never returns Teams HTML', async () => {
    const result = await unit.getChatMessages(
      GetChatMessagesInputSchema.parse({ chatId: 'chat-1' }),
      context,
      request,
    );

    expect(result.messages[0]?.content).toBe('Deploy is green.');
    expect(result.messages[0]?.content).not.toContain('<p>');
  });

  it('returns the full ISO timestamp rather than a truncated one', async () => {
    const result = await unit.getChatMessages(
      GetChatMessagesInputSchema.parse({ chatId: 'chat-1' }),
      context,
      request,
    );

    expect(result.messages[0]?.createdDateTime).toBe('2026-07-14T07:01:01.123Z');
  });

  // contentType named the format of a payload that is no longer returned, so it
  // could only mislead a reader of the normalized text beside it.
  it('omits contentType from the message', async () => {
    const result = await unit.getChatMessages(
      GetChatMessagesInputSchema.parse({ chatId: 'chat-1' }),
      context,
      request,
    );

    expect(result.messages[0]).not.toHaveProperty('contentType');
  });

  it('excludes system messages unless asked for them', async () => {
    await unit.getChatMessages(
      GetChatMessagesInputSchema.parse({ chatId: 'chat-1' }),
      context,
      request,
    );

    expect(getChatMessages).toHaveBeenCalledWith(
      'user-profile-1',
      'chat-1',
      20,
      expect.objectContaining({ excludeSystemMessages: true }),
    );
  });
});

describe('GetChannelMessagesTool', () => {
  let unit: GetChannelMessagesTool;
  let getChannelMessages: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    getChannelMessages = vi.fn().mockResolvedValue([htmlMessage]);

    ({ unit } = await TestBed.solitary(GetChannelMessagesTool)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => undefined }))
      .mock(ChatService)
      .impl(() => ({ getChannelMessages }))
      .compile());
  });

  it('normalizes the body and returns the full ISO timestamp', async () => {
    const result = await unit.getChannelMessages(
      GetChannelMessagesInputSchema.parse({ teamId: 'team-1', channelId: 'channel-1' }),
      context,
      request,
    );

    expect(result.messages[0]).toMatchObject({
      content: 'Deploy is green.',
      createdDateTime: '2026-07-14T07:01:01.123Z',
      senderDisplayName: 'Carol Lee',
    });
    expect(result.messages[0]).not.toHaveProperty('contentType');
  });
});
