import { type PageCollection } from '@microsoft/microsoft-graph-client';
import { ConflictException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  collectAllPages,
  collectUntil,
  GRAPH_MAX_ITEMS,
  GRAPH_PAGE_SIZE,
} from '~/msgraph/graph-pagination';
import { MsChat, MsChatMessage, MsChatMessageSchema, MsChatSchema } from './chat.dtos';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
  ) {}

  @Span()
  public async listChats(
    userProfileId: string,
    limit = 50,
  ): Promise<{ chats: MsChat[]; hasMore: boolean }> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Fetching chats from Microsoft Graph');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    // Deliberately single-page (NOT PageIterator): this is a bounded "recent
    // chats" window that must report an accurate `hasMore`. PageIterator hides
    // the page boundary and cannot distinguish "stopped at limit" from "no more
    // data", so it would re-introduce the `count === limit` false positive.
    const response: PageCollection = await client
      .api('/me/chats')
      .expand('members')
      .top(limit)
      .select('id,chatType,topic,members')
      .get();

    const chats = z.array(MsChatSchema).parse(response.value);
    // Report the real "more results" signal from Graph rather than inferring
    // truncation from `count === limit`, which is wrong when the user has
    // exactly `limit` chats and no further pages.
    const hasMore = Boolean(response['@odata.nextLink']);

    span?.setAttribute('result_count', chats.length);
    this.logger.debug({ userProfileId, count: chats.length }, 'Retrieved chats');

    return { chats, hasMore };
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

    // Graph does not support a server-side messageType filter on the chat and
    // channel message endpoints, so when excluding system messages we must page
    // through them client-side to still return up to `limit` user messages.
    const raw = await collectUntil(client, response, {
      limit,
      // Mirror MsChatMessageSchema's `messageType` default: Graph occasionally
      // omits the field, and the schema treats a missing type as a normal
      // 'message', so a raw `=== 'message'` check would wrongly drop those.
      filter: excludeSystemMessages ? (m) => (m.messageType ?? 'message') === 'message' : undefined,
    });
    const messages = z.array(MsChatMessageSchema).parse(raw);

    span?.setAttribute('result_count', messages.length);
    this.logger.debug({ userProfileId, chatId, count: messages.length }, 'Retrieved chat messages');

    return messages;
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
    const [{ chats, truncated }, me] = await Promise.all([
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
      span?.addEvent('chat not found', { truncated });
      // When the chat list was capped, the target may simply be beyond the cap
      // rather than non-existent — say so instead of a flat "not found".
      throw new NotFoundException(
        truncated
          ? `Chat "${identifier}" not found in your ${GRAPH_MAX_ITEMS} most recent chats. If it is an older chat, open it in Teams first or use a more specific identifier.`
          : `Chat "${identifier}" not found`,
      );
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

  // Pages through all of the user's chats so chat resolution is not limited to
  // the most recent window (unlike `listChats`, which is intentionally bounded
  // for the list tool).
  private async fetchAllChats(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
  ): Promise<{ chats: MsChat[]; truncated: boolean }> {
    const response = await client
      .api('/me/chats')
      .expand('members')
      .top(GRAPH_PAGE_SIZE)
      .select('id,chatType,topic,members')
      .get();

    const { items, truncated } = await collectAllPages(client, response, {
      label: 'resolveChatByNameOrMember',
    });
    return { chats: z.array(MsChatSchema).parse(items), truncated };
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

    const raw = await collectUntil(client, response, {
      limit,
      // Mirror MsChatMessageSchema's `messageType` default: Graph occasionally
      // omits the field, and the schema treats a missing type as a normal
      // 'message', so a raw `=== 'message'` check would wrongly drop those.
      filter: excludeSystemMessages ? (m) => (m.messageType ?? 'message') === 'message' : undefined,
    });
    const messages = z.array(MsChatMessageSchema).parse(raw);

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
