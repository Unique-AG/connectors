import { ConflictException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MsChat, MsChatMessage, MsChatMessageSchema, MsChatSchema } from './chat.dtos';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  // Safety cap on Graph pagination so a pathological account cannot cause an
  // unbounded number of follow-up requests.
  private static readonly MAX_PAGES = 20;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
  ) {}

  @Span()
  public async listChats(userProfileId: string, limit = 50): Promise<MsChat[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Fetching chats from Microsoft Graph');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api('/me/chats')
      .expand('members')
      .top(limit)
      .select('id,chatType,topic,members')
      .get();

    const chats = z.array(MsChatSchema).parse(response.value);

    span?.setAttribute('result_count', chats.length);
    this.logger.debug({ userProfileId, count: chats.length }, 'Retrieved chats');

    return chats;
  }

  @Span()
  public async getChatMessages(
    userProfileId: string,
    chatId: string,
    limit: number,
    options: { orderBy?: string; excludeSystemMessages?: boolean } = {},
  ): Promise<MsChatMessage[]> {
    const { orderBy = 'createdDateTime desc', excludeSystemMessages = false } = options;
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('limit', limit);

    this.logger.debug(
      { userProfileId, chatId, limit },
      'Fetching chat messages from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/chats/${chatId}/messages`)
      .top(limit)
      .orderby(orderBy)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    const messages = await this.collectMessages(client, response, limit, excludeSystemMessages);

    span?.setAttribute('result_count', messages.length);
    this.logger.debug({ userProfileId, chatId, count: messages.length }, 'Retrieved chat messages');

    return messages;
  }

  // Pages through Graph `@odata.nextLink` until `limit` messages are collected
  // (optionally excluding system messages) or the pages / page cap run out.
  // Graph does not support a server-side messageType filter on the chat and
  // channel message endpoints, so excluding system messages client-side
  // without paging could return far fewer than `limit` user messages.
  private async collectMessages(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    firstResponse: { value: unknown; '@odata.nextLink'?: string },
    limit: number,
    excludeSystemMessages: boolean,
  ): Promise<MsChatMessage[]> {
    const collected: MsChatMessage[] = [];
    let response = firstResponse;

    for (let page = 0; page < ChatService.MAX_PAGES; page++) {
      const parsed = z.array(MsChatMessageSchema).parse(response.value);
      for (const message of parsed) {
        if (excludeSystemMessages && message.messageType !== 'message') {
          continue;
        }
        collected.push(message);
      }

      const nextLink = response['@odata.nextLink'];
      if (collected.length >= limit || !nextLink) {
        break;
      }
      response = await client.api(nextLink).get();
    }

    return collected.slice(0, limit);
  }

  @Span()
  public async resolveChatByNameOrMember(
    userProfileId: string,
    identifier: string,
  ): Promise<MsChat> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Resolving chat by topic or member name');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const [chats, me] = await Promise.all([
      this.fetchAllChats(client),
      client.api('/me').select('id').get() as Promise<{ id: string }>,
    ]);
    const currentUserId = me.id;
    const lowerIdentifier = identifier.toLowerCase();

    // Exact case-insensitive match on the chat topic, or on a member's display
    // name. Member matching applies to both 1:1 and group chats — group chats
    // are frequently topicless and only addressable by member. The current user
    // is excluded from member matching so searching one's own name does not
    // match every chat.
    const matches = chats.filter((c) => {
      if (c.topic?.toLowerCase() === lowerIdentifier) {
        return true;
      }
      return c.members.some(
        (m) => m.userId !== currentUserId && m.displayName?.toLowerCase() === lowerIdentifier,
      );
    });

    if (matches.length === 0) {
      span?.addEvent('chat not found');
      throw new NotFoundException(`Chat "${identifier}" not found`);
    }

    // TODO: replace with context.elicitInput() once exposed on Context interface
    // in mcp-server-module. Present a picker with chat type, topic/member name,
    // and last message timestamp so the user can select the intended chat.
    if (matches.length > 1) {
      const matchDescriptions = matches
        .map((c) => c.topic ?? c.members.map((m) => m.displayName).join(', '))
        .join('; ');
      span?.addEvent('ambiguous chat identifier', { matchCount: matches.length });
      throw new ConflictException(
        `Identifier "${identifier}" matches multiple chats: ${matchDescriptions}. Please be more specific.`,
      );
    }

    // matches.length === 1 is guaranteed by the checks above
    const [chat] = matches as [MsChat];
    span?.setAttribute('resolved_chat_id', chat.id);
    return chat;
  }

  // Pages through all of the user's chats, following Graph `@odata.nextLink`
  // up to the page cap, so chat resolution is not limited to the most recent
  // window (unlike `listChats`, which is intentionally bounded for the list
  // tool).
  private async fetchAllChats(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
  ): Promise<MsChat[]> {
    const all: MsChat[] = [];
    let response = await client
      .api('/me/chats')
      .expand('members')
      .top(50)
      .select('id,chatType,topic,members')
      .get();

    for (let page = 0; page < ChatService.MAX_PAGES; page++) {
      all.push(...z.array(MsChatSchema).parse(response.value));
      const nextLink = response['@odata.nextLink'] as string | undefined;
      if (!nextLink) {
        break;
      }
      response = await client.api(nextLink).get();
    }

    return all;
  }

  @Span()
  public async getChannelMessages(
    userProfileId: string,
    teamId: string,
    channelId: string,
    limit: number,
    options: { orderBy?: string; excludeSystemMessages?: boolean } = {},
  ): Promise<MsChatMessage[]> {
    const { orderBy = 'createdDateTime desc', excludeSystemMessages = false } = options;
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);
    span?.setAttribute('channel_id', channelId);
    span?.setAttribute('limit', limit);

    this.logger.debug(
      { userProfileId, teamId, channelId, limit },
      'Fetching channel messages from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/teams/${teamId}/channels/${channelId}/messages`)
      .top(limit)
      .orderby(orderBy)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    const messages = await this.collectMessages(client, response, limit, excludeSystemMessages);

    span?.setAttribute('result_count', messages.length);
    this.logger.debug(
      { userProfileId, teamId, channelId, count: messages.length },
      'Retrieved channel messages',
    );

    return messages;
  }

  @Span()
  public async getChatMessageById(
    userProfileId: string,
    chatId: string,
    messageId: string,
  ): Promise<MsChatMessage> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('message_id', messageId);

    this.logger.debug(
      { userProfileId, chatId, messageId },
      'Fetching chat message by id from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/chats/${chatId}/messages/${messageId}`)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    return MsChatMessageSchema.parse(response);
  }

  @Span()
  public async getChannelMessageById(
    userProfileId: string,
    teamId: string,
    channelId: string,
    messageId: string,
  ): Promise<MsChatMessage> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);
    span?.setAttribute('channel_id', channelId);
    span?.setAttribute('message_id', messageId);

    this.logger.debug(
      { userProfileId, teamId, channelId, messageId },
      'Fetching channel message by id from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/teams/${teamId}/channels/${channelId}/messages/${messageId}`)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    return MsChatMessageSchema.parse(response);
  }

  @Span()
  public async sendChatMessage(
    userProfileId: string,
    chatId: string,
    message: string,
  ): Promise<{ id: string }> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('message_length', message.length);

    this.logger.debug({ userProfileId, chatId }, 'Sending message to chat');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api(`/chats/${chatId}/messages`).post({
      body: {
        contentType: 'text',
        content: message,
      },
    });

    const result = z.object({ id: z.string() }).parse(response);

    span?.setAttribute('message_id', result.id);
    this.logger.log({ userProfileId, chatId, messageId: result.id }, 'Message sent to chat');

    return result;
  }
}
