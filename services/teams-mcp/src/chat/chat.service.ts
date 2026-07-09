import { type PageCollection } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { collectUntil } from '~/msgraph/graph-pagination';
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
    // Single-page by design (not collectAllPages): a bounded "recent chats"
    // window with an accurate `hasMore`. $orderby is required for "most recent"
    // — /me/chats is not sorted by activity by default.
    const response: PageCollection = await client
      .api('/me/chats')
      .expand('members,lastMessagePreview')
      .top(limit)
      .orderby('lastMessagePreview/createdDateTime desc')
      .select('id,chatType,topic,members,createdDateTime')
      .get();

    const chats = z.array(MsChatSchema).parse(response.value);
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
      .select('id,createdDateTime,from,body,attachments,messageType,deletedDateTime')
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
      .select('id,createdDateTime,from,body,attachments,messageType,deletedDateTime')
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
      .select('id,createdDateTime,from,body,attachments,messageType,deletedDateTime')
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
      .select('id,createdDateTime,from,body,attachments,messageType,deletedDateTime')
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
