import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { describe, expect, it, vi } from 'vitest';
import { ChannelService } from '../channel.service';
import { MsChatSchema } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { ListChannelsTool } from './list-channels.tool';
import { ListChatsTool } from './list-chats.tool';

const request = { user: { userProfileId: 'user-profile-1' } } as McpAuthenticatedRequest;
const context = {} as Context;

describe('ListChatsTool', () => {
  it('returns each chat with a title and a Teams link', async () => {
    const chat = MsChatSchema.parse({
      id: '19:launch@thread.v2',
      chatType: 'group',
      topic: null,
      members: [
        { userId: 'user-1', displayName: 'Alice Smith' },
        { userId: 'user-2', displayName: 'Ben Ortiz' },
      ],
    });
    const { unit } = await TestBed.solitary(ListChatsTool)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => undefined }))
      .mock(ChatService)
      .impl(() => ({ listChats: vi.fn().mockResolvedValue([chat]) }))
      .compile();

    const result = await unit.listChats(
      { limit: 25, includeMemberEmails: false },
      context,
      request,
    );

    expect(result.chats[0]).toMatchObject({
      title: 'Alice Smith, Ben Ortiz',
      webUrl: 'https://teams.microsoft.com/l/chat/19%3Alaunch%40thread.v2/conversations',
    });
  });
});

describe('ListChannelsTool', () => {
  const channel = {
    id: '19:general@thread.tacv2',
    displayName: 'General',
    description: null,
    createdDateTime: null,
    membershipType: 'standard',
  };

  async function listChannelsReturning(channels: unknown[]) {
    const { unit } = await TestBed.solitary(ListChannelsTool)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => undefined }))
      .mock(ChannelService)
      .impl(() => ({ listChannels: vi.fn().mockResolvedValue(channels) }))
      .compile();

    return unit.listChannels({ teamId: 'team-1', includeDescriptions: false }, context, request);
  }

  it('returns each channel with the Teams link Graph sends', async () => {
    const webUrl =
      'https://teams.microsoft.com/l/channel/19%3Ageneral%40thread.tacv2/General?groupId=team-1';

    const result = await listChannelsReturning([{ ...channel, webUrl }]);

    expect(result.channels[0]).toMatchObject({ displayName: 'General', webUrl });
  });

  it('returns a null link when Graph sends none', async () => {
    const result = await listChannelsReturning([channel]);

    expect(result.channels[0]?.webUrl).toBeNull();
  });
});
