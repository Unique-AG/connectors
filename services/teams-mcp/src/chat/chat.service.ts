import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MsChat, MsChatMessage, MsChatMessageSchema, MsChatSchema } from './chat.dtos';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

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
    orderBy = 'createdDateTime desc',
  ): Promise<MsChatMessage[]> {
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
      .select('id,createdDateTime,from,body,attachments')
      .get();

    const messages = z.array(MsChatMessageSchema).parse(response.value);

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
    span?.setAttribute('identifier', identifier);

    this.logger.debug({ userProfileId, identifier }, 'Resolving chat by topic or member name');

    const chats = await this.listChats(userProfileId);
    const lowerIdentifier = identifier.toLowerCase();

    // NOTE: match priority — topic substring first, then member display name for 1:1 chats.
    // Group chats without a topic are only matchable by topic; oneOnOne chats fall back to member name.
    const chat = chats.find((c) => {
      if (c.topic?.toLowerCase().includes(lowerIdentifier)) {
        return true;
      }
      if (c.chatType === 'oneOnOne') {
        return c.members.some((m) => m.displayName?.toLowerCase().includes(lowerIdentifier));
      }
      return false;
    });

    if (!chat) {
      span?.addEvent('chat not found', { identifier });
      throw new NotFoundException(`Chat "${identifier}" not found`);
    }

    span?.setAttribute('resolved_chat_id', chat.id);
    return chat;
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
